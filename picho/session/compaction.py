"""
Context compaction for long sessions.

Simple token-based compaction with LLM summarization.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import (
    SessionMessageEntry,
    SessionEntryType,
    message_to_dict,
)
from ..logger import get_logger

_log = get_logger(__name__)


SUMMARIZATION_PROMPT = """Please summarize the following conversation concisely:

1. User's main goals
2. Work completed
3. Important decisions and conclusions
4. Files involved (read, modified)
5. Unfinished tasks

Keep it brief but useful for continuing the conversation.

<conversation>
{conversation}
</conversation>

Summary:"""


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000
    trigger_threshold: int = 100000


@dataclass
class CompactionPreparation:
    messages_to_summarize: list[dict]
    first_kept_entry_id: str
    tokens_before: int
    entries_to_summarize: list[SessionEntryType]


def estimate_tokens(message: dict) -> int:
    role = message.get("role", "")
    content = message.get("content", "")

    chars = 0

    if isinstance(content, str):
        chars = len(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    chars += len(block.get("text", ""))
                elif block.get("type") == "thinking":
                    chars += len(block.get("thinking", ""))
                elif block.get("type") == "toolCall":
                    name = block.get("name", "")
                    args = block.get("arguments", {})
                    chars += len(name) + len(str(args))
                elif block.get("type") == "image":
                    chars += 4800

    if role == "compaction_summary":
        chars = len(message.get("summary", ""))
    elif role == "branch_summary":
        chars = len(message.get("summary", ""))

    return max(1, chars // 4)


def _normalize_message(message) -> dict:
    if isinstance(message, dict):
        return message
    return message_to_dict(message)


def calculate_total_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(_normalize_message(msg))
    return total


def get_last_assistant_usage(messages: list[dict]) -> dict | None:
    for i in range(len(messages) - 1, -1, -1):
        msg = _normalize_message(messages[i])
        if msg.get("role") == "assistant":
            usage = msg.get("usage")
            if usage:
                return usage
    return None


def estimate_context_tokens(messages: list[dict]) -> int:
    usage = get_last_assistant_usage(messages)

    if usage:
        usage_tokens = (
            usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + usage.get("cache_read", 0)
            + usage.get("cache_write", 0)
        )

        last_usage_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            msg = _normalize_message(messages[i])
            if msg.get("role") == "assistant" and msg.get("usage"):
                last_usage_idx = i
                break

        if last_usage_idx >= 0:
            trailing = 0
            for i in range(last_usage_idx + 1, len(messages)):
                trailing += estimate_tokens(_normalize_message(messages[i]))
            return usage_tokens + trailing

        return usage_tokens

    return calculate_total_tokens(messages)


def should_compact(
    context_tokens: int,
    context_window: int,
    settings: CompactionSettings,
) -> bool:
    if not settings.enabled:
        return False
    return context_tokens > context_window - settings.reserve_tokens


def find_valid_cut_points(
    entries: list[SessionEntryType],
    start_idx: int,
    end_idx: int,
) -> list[int]:
    cut_points = []

    for i in range(start_idx, end_idx):
        entry = entries[i]
        if isinstance(entry, SessionMessageEntry):
            role = entry.message.get("role", "")
            if role in ("user", "assistant"):
                cut_points.append(i)

    return cut_points


def prepare_compaction(
    entries: list[SessionEntryType],
    settings: CompactionSettings,
    context_window: int = 128000,
) -> CompactionPreparation | None:
    _log.debug(
        f"Preparing compaction: entries_count={len(entries)} context_window={context_window}"
    )
    if len(entries) < 2:
        _log.debug("Not enough entries for compaction")
        return None

    messages = []
    for entry in entries:
        if isinstance(entry, SessionMessageEntry):
            messages.append(entry.message)

    tokens_before = estimate_context_tokens(messages)
    _log.debug(f"Context tokens before compaction: {tokens_before}")

    if not should_compact(tokens_before, context_window, settings):
        _log.debug("No compaction needed")
        return None

    target_tokens = settings.keep_recent_tokens
    recent_tokens = 0
    first_kept_idx = len(entries)

    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if isinstance(entry, SessionMessageEntry):
            tokens = estimate_tokens(entry.message)
            recent_tokens += tokens

            if recent_tokens > target_tokens:
                cut_points = find_valid_cut_points(entries, 0, i + 1)
                if cut_points:
                    first_kept_idx = cut_points[-1] + 1
                else:
                    first_kept_idx = i + 1
                break

    if first_kept_idx <= 1:
        first_kept_idx = 1

    entries_to_summarize = entries[:first_kept_idx]
    messages_to_summarize = []

    for entry in entries_to_summarize:
        if isinstance(entry, SessionMessageEntry):
            messages_to_summarize.append(entry.message)

    first_kept_entry_id = (
        entries[first_kept_idx].id if first_kept_idx < len(entries) else ""
    )

    return CompactionPreparation(
        messages_to_summarize=messages_to_summarize,
        first_kept_entry_id=first_kept_entry_id,
        tokens_before=tokens_before,
        entries_to_summarize=entries_to_summarize,
    )


def serialize_conversation(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        msg = _normalize_message(msg)
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        text_parts.append(f"[Thinking: {block.get('thinking', '')}]")
                    elif block.get("type") == "toolCall":
                        text_parts.append(f"[Tool: {block.get('name', '')}]")
            content = " ".join(text_parts)

        lines.append(f"{role.upper()}: {content}")

    return "\n\n".join(lines)


async def generate_summary(
    messages: list[dict],
    model,
    max_tokens: int = 4096,
) -> str:
    _log.debug(f"Generating summary for {len(messages)} messages")
    conversation = serialize_conversation(messages)
    prompt = SUMMARIZATION_PROMPT.format(conversation=conversation)

    try:
        from ..provider.types import UserMessage, TextContent

        msg = UserMessage(content=[TextContent(type="text", text=prompt)])

        _log.debug("Calling model for summary generation")
        response = await model.complete([msg], max_tokens=max_tokens)

        if response and hasattr(response, "content"):
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text

        return "Summary unavailable"
    except Exception as e:
        return f"Summary generation failed: {str(e)}"


def extract_file_ops(messages: list[dict]) -> dict[str, list[str]]:
    read_files = set()
    modified_files = set()

    for msg in messages:
        msg = _normalize_message(msg)
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        name = block.get("name", "")
                        args = block.get("arguments", {})
                        path = args.get("file_path") or args.get("path", "")

                        if name == "read" and path:
                            read_files.add(path)
                        elif name in ("write", "edit") and path:
                            modified_files.add(path)

    return {
        "read_files": sorted(list(read_files)),
        "modified_files": sorted(list(modified_files)),
    }

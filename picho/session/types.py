"""
Session types for picho

Simple session management with JSONL storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal, Union, TypeAlias
import uuid
import json

from ..provider.types import (
    AssistantMessage,
    ImageBase64Content,
    ImageFileIdContent,
    ImageUrlContent,
    Message,
    StopReason,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
    VideoFileIdContent,
)


CURRENT_SESSION_VERSION = 2


@dataclass
class SessionHeader:
    type: str = "session"
    version: int = CURRENT_SESSION_VERSION
    id: str = ""
    timestamp: str = ""
    cwd: str = ""
    parent_session: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionHeader":
        return cls(
            type=d.get("type", "session"),
            version=d.get("version", 1),
            id=d.get("id", ""),
            timestamp=d.get("timestamp", ""),
            cwd=d.get("cwd", ""),
            parent_session=d.get("parent_session"),
        )


@dataclass
class SessionEntry:
    type: str = ""
    id: str = ""
    parent_id: str | None = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionMessageEntry(SessionEntry):
    type: str = "message"
    message: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["message"] = self.message
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMessageEntry":
        return cls(
            type=d.get("type", "message"),
            id=d.get("id", ""),
            parent_id=d.get("parent_id"),
            timestamp=d.get("timestamp", ""),
            message=d.get("message", {}),
        )


@dataclass
class ModelChangeEntry(SessionEntry):
    type: str = "model_change"
    provider: str = ""
    model_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ModelChangeEntry":
        return cls(
            type=d.get("type", "model_change"),
            id=d.get("id", ""),
            parent_id=d.get("parent_id"),
            timestamp=d.get("timestamp", ""),
            provider=d.get("provider", ""),
            model_id=d.get("model_id", ""),
        )


@dataclass
class ThinkingLevelChangeEntry(SessionEntry):
    type: str = "thinking_level_change"
    thinking_level: str = "off"

    @classmethod
    def from_dict(cls, d: dict) -> "ThinkingLevelChangeEntry":
        return cls(
            type=d.get("type", "thinking_level_change"),
            id=d.get("id", ""),
            parent_id=d.get("parent_id"),
            timestamp=d.get("timestamp", ""),
            thinking_level=d.get("thinking_level", "off"),
        )


@dataclass
class CompactionEntry(SessionEntry):
    type: str = "compaction"
    summary: str = ""
    first_kept_entry_id: str = ""
    tokens_before: int = 0
    details: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "CompactionEntry":
        return cls(
            type=d.get("type", "compaction"),
            id=d.get("id", ""),
            parent_id=d.get("parent_id"),
            timestamp=d.get("timestamp", ""),
            summary=d.get("summary", ""),
            first_kept_entry_id=d.get("first_kept_entry_id", ""),
            tokens_before=d.get("tokens_before", 0),
            details=d.get("details", {}),
        )


@dataclass
class BranchSummaryEntry(SessionEntry):
    type: str = "branch_summary"
    from_id: str = ""
    summary: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "BranchSummaryEntry":
        return cls(
            type=d.get("type", "branch_summary"),
            id=d.get("id", ""),
            parent_id=d.get("parent_id"),
            timestamp=d.get("timestamp", ""),
            from_id=d.get("from_id", ""),
            summary=d.get("summary", ""),
        )


SessionEntryType: TypeAlias = Union[
    SessionMessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
    CompactionEntry,
    BranchSummaryEntry,
]


@dataclass
class SessionInfo:
    path: str
    id: str
    cwd: str
    name: str | None
    parent_session_path: str | None
    created: datetime
    modified: datetime
    message_count: int
    first_message: str


@dataclass
class SessionContext:
    messages: list[Message] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    thinking_level: str = "off"
    model: dict | None = None


def generate_id() -> str:
    return uuid.uuid4().hex[:8]


def get_timestamp() -> str:
    return datetime.now().isoformat()


def message_to_dict(msg: Message) -> dict:
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    if hasattr(msg, "__dataclass_fields__"):
        d = asdict(msg)
        d["role"] = msg.role
        return d
    return dict(msg)


def _dict_to_usage(d: dict[str, Any] | None) -> Usage:
    data = d or {}
    return Usage(
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        cache_read=data.get("cache_read", 0),
        cache_write=data.get("cache_write", 0),
    )


def _dict_to_content_block(block: Any):
    if hasattr(block, "__dataclass_fields__"):
        return block

    if isinstance(block, str):
        return TextContent(type="text", text=block)

    if not isinstance(block, dict):
        raise ValueError(f"Unsupported content block: {type(block).__name__}")

    block_type = block.get("type", "text")
    if block_type == "text":
        return TextContent(type="text", text=block.get("text", ""))
    if block_type == "thinking":
        return ThinkingContent(type="thinking", thinking=block.get("thinking", ""))
    if block_type == "toolCall":
        return ToolCall(
            type="toolCall",
            id=block.get("id", ""),
            name=block.get("name", ""),
            arguments=block.get("arguments", {}) or {},
            _args_str=block.get("_args_str", ""),
        )
    if block_type == "image_base64":
        return ImageBase64Content(
            type="image_base64",
            data=block.get("data", ""),
            mime_type=block.get("mime_type", "image/png"),
        )
    if block_type == "image_url":
        return ImageUrlContent(type="image_url", url=block.get("url", ""))
    if block_type == "image_file_id":
        return ImageFileIdContent(
            type="image_file_id",
            file_id=block.get("file_id", ""),
        )
    if block_type == "video_file_id":
        return VideoFileIdContent(
            type="video_file_id",
            file_path=block.get("file_path"),
            file_id=block.get("file_id"),
        )

    raise ValueError(f"Unsupported content block type: {block_type}")


def _dict_to_content_blocks(
    content: str | list[dict[str, Any]] | list[Any] | None,
    *,
    role: Literal["user", "assistant", "toolResult"],
) -> str | list[Any]:
    if role == "user" and isinstance(content, str):
        return content

    if content is None:
        return [] if role != "user" else ""

    if isinstance(content, str):
        return [TextContent(type="text", text=content)]

    return [_dict_to_content_block(block) for block in content]


def dict_to_message(d: dict) -> Message:
    role = d.get("role", "")
    if role == "user":
        return UserMessage(
            role="user",
            content=_dict_to_content_blocks(d.get("content", ""), role="user"),
            timestamp=d.get("timestamp", 0),
        )

    if role == "assistant":
        stop_reason = d.get("stop_reason", StopReason.STOP.value)
        return AssistantMessage(
            role="assistant",
            content=_dict_to_content_blocks(d.get("content", []), role="assistant"),
            api=d.get("api", ""),
            provider=d.get("provider", ""),
            model=d.get("model", ""),
            usage=_dict_to_usage(d.get("usage")),
            stop_reason=StopReason(stop_reason),
            error_message=d.get("error_message"),
            timestamp=d.get("timestamp", 0),
        )

    if role == "toolResult":
        return ToolResultMessage(
            role="toolResult",
            tool_call_id=d.get("tool_call_id", ""),
            tool_name=d.get("tool_name", ""),
            content=_dict_to_content_blocks(d.get("content", []), role="toolResult"),
            is_error=d.get("is_error", False),
            details=d.get("details"),
        )

    raise ValueError(f"Unsupported message role: {role}")


def parse_entry(line: str) -> SessionHeader | SessionEntryType | None:
    try:
        d = json.loads(line)
        entry_type = d.get("type", "")

        if entry_type == "session":
            return SessionHeader.from_dict(d)
        elif entry_type == "message":
            return SessionMessageEntry.from_dict(d)
        elif entry_type == "model_change":
            return ModelChangeEntry.from_dict(d)
        elif entry_type == "thinking_level_change":
            return ThinkingLevelChangeEntry.from_dict(d)
        elif entry_type == "compaction":
            return CompactionEntry.from_dict(d)
        elif entry_type == "branch_summary":
            return BranchSummaryEntry.from_dict(d)
        else:
            return None
    except json.JSONDecodeError:
        return None

"""
Anthropic Messages API Provider

Supports Claude Messages streaming with tool use, thinking, and image input.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import Model
from ..stream import (
    AssistantMessageEvent,
    AssistantMessageEventType,
    EventStream,
    StreamEvent,
)
from ..types import (
    AssistantMessage,
    Context,
    ImageBase64Content,
    ImageUrlContent,
    StopReason,
    StreamOptions,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
    extract_text_content,
    normalize_content_blocks,
)
from ...logger import format_exception, get_logger, log_exception
from ...tool import Tool

_log = get_logger(__name__)

default_anthropic_model = "claude-sonnet-4-5"
default_anthropic_base_url = "https://api.anthropic.com"
default_anthropic_env = "ANTHROPIC_API_KEY"


def _thinking_budget(level: str) -> int:
    budgets = {
        "minimal": 1024,
        "low": 2048,
        "medium": 4096,
        "high": 8192,
        "xhigh": 16384,
    }
    return budgets.get(level, 4096)


def _map_stop_reason(reason: str | None) -> StopReason:
    if reason in (None, "end_turn", "stop_sequence", "pause_turn"):
        return StopReason.STOP
    if reason == "max_tokens":
        return StopReason.LENGTH
    if reason == "tool_use":
        return StopReason.TOOL_USE
    return StopReason.ERROR


def _parse_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _tool_result_id(tool_call_id: str) -> str:
    return tool_call_id.split("|", 1)[0]


def _convert_tool_result_content(
    message: ToolResultMessage,
) -> str | list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    content = normalize_content_blocks(message.content)
    text = extract_text_content(content)
    if text:
        blocks.append({"type": "text", "text": text})

    for block in content:
        if isinstance(block, ImageBase64Content):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block.mime_type,
                        "data": block.data,
                    },
                }
            )
        elif isinstance(block, ImageUrlContent):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": block.url,
                    },
                }
            )

    if not blocks:
        return ""
    if len(blocks) == 1 and blocks[0]["type"] == "text":
        return blocks[0]["text"]
    return blocks


def to_anthropic_messages(
    context: Context, input_types: list[str]
) -> tuple[list[dict[str, Any]], str]:
    messages: list[dict[str, Any]] = []
    supports_image = "image" in input_types

    for msg in context.messages:
        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                if msg.content.strip():
                    messages.append({"role": "user", "content": msg.content})
                continue

            content: list[dict[str, Any]] = []
            for block in msg.content:
                if isinstance(block, TextContent) and block.text:
                    content.append({"type": "text", "text": block.text})
                elif supports_image and isinstance(block, ImageBase64Content):
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": block.mime_type,
                                "data": block.data,
                            },
                        }
                    )
                elif supports_image and isinstance(block, ImageUrlContent):
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": block.url,
                            },
                        }
                    )
            if content:
                messages.append({"role": "user", "content": content})

        elif isinstance(msg, AssistantMessage):
            content: list[dict[str, Any]] = []
            for block in msg.content:
                if isinstance(block, TextContent) and block.text:
                    content.append({"type": "text", "text": block.text})
                elif isinstance(block, ThinkingContent) and block.thinking.strip():
                    # picho does not persist Anthropic thinking signatures yet, so
                    # prior thinking must degrade to plain text for replay.
                    content.append({"type": "text", "text": block.thinking})
                elif isinstance(block, ToolCall):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.arguments,
                        }
                    )
            if content:
                messages.append({"role": "assistant", "content": content})
            elif msg.error_message:
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": f"[Error: {msg.error_message}]"}
                        ],
                    }
                )

        elif isinstance(msg, ToolResultMessage):
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": _tool_result_id(msg.tool_call_id),
                            "content": _convert_tool_result_content(msg),
                            "is_error": msg.is_error,
                        }
                    ],
                }
            )

    return messages, context.instructions


def _convert_anthropic_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": tool.parameters.type,
                "properties": tool.parameters.properties,
                "required": tool.parameters.required,
            }
            if tool.parameters
            else {"type": "object", "properties": {}, "required": []},
        }
        for tool in tools
    ]


class AnthropicModel(Model):
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.require_api_key(), base_url=self.base_url)
        messages, instructions = to_anthropic_messages(context, self.input_types)
        tools = _convert_anthropic_tools(context.tools) if context.tools else None

        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def run_stream() -> None:
            _log.info(
                "Anthropic stream start: model=%s messages=%s tools=%s",
                self.model_name,
                len(messages),
                len(tools or []),
            )
            content_blocks: list[Any] = []
            usage = Usage()
            stop_reason = StopReason.STOP
            block_by_index: dict[int, Any] = {}

            try:
                params: dict[str, Any] = {
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": (
                        options.max_tokens
                        if options and options.max_tokens is not None
                        else self.extra.get("max_tokens", 4096)
                    ),
                    "stream": True,
                }

                if instructions:
                    params["system"] = instructions
                if tools:
                    params["tools"] = tools
                if options:
                    if options.temperature is not None:
                        params["temperature"] = options.temperature
                    if options.extra_headers is not None:
                        params["extra_headers"] = options.extra_headers
                    if options.extra_query is not None:
                        params["extra_query"] = options.extra_query
                    if options.extra_body is not None:
                        params["extra_body"] = options.extra_body
                    if options.timeout is not None:
                        params["timeout"] = options.timeout
                    if options.thinking_level == "off":
                        params["thinking"] = {"type": "disabled"}
                    elif options.thinking_level != "auto":
                        params["thinking"] = {
                            "type": "enabled",
                            "budget_tokens": _thinking_budget(options.thinking_level),
                        }

                response = await client.messages.create(**params)
                stream.push(StreamEvent(type="message_start"))

                async for event in response:
                    if options and options.signal and options.signal.is_set():
                        stop_reason = StopReason.ABORTED
                        break

                    event_type = getattr(event, "type", None)

                    if event_type == "message_start":
                        msg_usage = getattr(
                            getattr(event, "message", None), "usage", None
                        )
                        if msg_usage:
                            usage = Usage(
                                input_tokens=getattr(msg_usage, "input_tokens", 0) or 0,
                                output_tokens=getattr(msg_usage, "output_tokens", 0)
                                or 0,
                                cache_read=getattr(
                                    msg_usage, "cache_read_input_tokens", 0
                                )
                                or 0,
                                cache_write=getattr(
                                    msg_usage, "cache_creation_input_tokens", 0
                                )
                                or 0,
                            )

                    elif event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        index = getattr(event, "index", len(content_blocks))
                        if block is None:
                            continue

                        if block.type == "text":
                            current = TextContent(type="text", text="")
                            content_blocks.append(current)
                            block_by_index[index] = current
                        elif block.type == "thinking":
                            current = ThinkingContent(type="thinking", thinking="")
                            content_blocks.append(current)
                            block_by_index[index] = current
                        elif block.type == "tool_use":
                            current = ToolCall(
                                type="toolCall",
                                id=getattr(block, "id", ""),
                                name=getattr(block, "name", ""),
                                arguments=getattr(block, "input", {}) or {},
                                _args_str="",
                            )
                            content_blocks.append(current)
                            block_by_index[index] = current
                            stream.push(
                                StreamEvent(
                                    type="tool_call_start",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TOOL_CALL_START,
                                        tool_call_id=current.id,
                                        tool_name=current.name,
                                    ),
                                )
                            )

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        block = block_by_index.get(getattr(event, "index", -1))
                        if delta is None or block is None:
                            continue

                        if delta.type == "text_delta" and isinstance(
                            block, TextContent
                        ):
                            block.text += delta.text
                            stream.push(
                                StreamEvent(
                                    type="content_delta",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TEXT_DELTA,
                                        delta=delta.text,
                                    ),
                                )
                            )
                        elif delta.type == "thinking_delta" and isinstance(
                            block, ThinkingContent
                        ):
                            block.thinking += delta.thinking
                            stream.push(
                                StreamEvent(
                                    type="thinking_delta",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.THINKING_DELTA,
                                        delta=delta.thinking,
                                    ),
                                )
                            )
                        elif delta.type == "input_json_delta" and isinstance(
                            block, ToolCall
                        ):
                            block._args_str += delta.partial_json
                            stream.push(
                                StreamEvent(
                                    type="tool_call_delta",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TOOL_CALL_DELTA,
                                        tool_call_id=block.id,
                                        delta=delta.partial_json,
                                    ),
                                )
                            )

                    elif event_type == "content_block_stop":
                        block = block_by_index.get(getattr(event, "index", -1))
                        if isinstance(block, ToolCall) and block._args_str:
                            block.arguments = _parse_json(block._args_str)

                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "stop_reason", None):
                            stop_reason = _map_stop_reason(delta.stop_reason)
                        event_usage = getattr(event, "usage", None)
                        if event_usage:
                            usage.input_tokens = (
                                getattr(event_usage, "input_tokens", usage.input_tokens)
                                or usage.input_tokens
                            )
                            usage.output_tokens = (
                                getattr(
                                    event_usage, "output_tokens", usage.output_tokens
                                )
                                or usage.output_tokens
                            )
                            usage.cache_read = (
                                getattr(
                                    event_usage,
                                    "cache_read_input_tokens",
                                    usage.cache_read,
                                )
                                or usage.cache_read
                            )
                            usage.cache_write = (
                                getattr(
                                    event_usage,
                                    "cache_creation_input_tokens",
                                    usage.cache_write,
                                )
                                or usage.cache_write
                            )

                message = AssistantMessage(
                    role="assistant",
                    content=content_blocks,
                    api="anthropic-messages",
                    provider=self.model_provider,
                    model=self.model_name,
                    usage=usage,
                    stop_reason=stop_reason,
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)
                _log.info(
                    "Anthropic stream end: stop_reason=%s usage_input=%s usage_output=%s",
                    stop_reason,
                    usage.input_tokens,
                    usage.output_tokens,
                )
            except Exception as error:
                error_detail = format_exception(error)
                log_exception(
                    _log,
                    "Anthropic stream error",
                    error,
                    model=self.model_name,
                )
                message = AssistantMessage(
                    role="assistant",
                    content=[TextContent(type="text", text="")],
                    api="anthropic-messages",
                    provider=self.model_provider,
                    model=self.model_name,
                    usage=usage,
                    stop_reason=StopReason.ERROR,
                    error_message=error_detail,
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.set_error(error)

        asyncio.create_task(run_stream())
        return stream

"""
Serialization helpers for observability payloads.
"""

from __future__ import annotations

import json
from typing import Any

from ..provider.types import (
    AssistantMessage,
    ImageBase64Content,
    ImageFileIdContent,
    ImageUrlContent,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
    VideoFileIdContent,
)
from ..tool import ToolResult

_MAX_TEXT_LENGTH = 2000
_MAX_COLLECTION_ITEMS = 20
_MAX_DEPTH = 5


def _clip_text(value: str, limit: int = _MAX_TEXT_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _serialize_content_block(block: Any, depth: int) -> Any:
    if isinstance(block, TextContent):
        return {"type": "text", "text": _clip_text(block.text)}
    if isinstance(block, ThinkingContent):
        return {"type": "thinking", "thinking": _clip_text(block.thinking)}
    if isinstance(block, ToolCall):
        return {
            "type": "tool_call",
            "id": block.id,
            "name": block.name,
            "arguments": serialize_value(block.arguments, depth=depth - 1),
        }
    if isinstance(block, ImageBase64Content):
        return {
            "type": "image_base64",
            "mime_type": block.mime_type,
            "content": "[image]",
        }
    if isinstance(block, ImageUrlContent):
        return {"type": "image_url", "url": block.url, "content": "[image]"}
    if isinstance(block, ImageFileIdContent):
        return {"type": "image_file_id", "file_id": block.file_id, "content": "[image]"}
    if isinstance(block, VideoFileIdContent):
        return {
            "type": "video_file_id",
            "file_id": block.file_id,
            "file_path": block.file_path,
            "content": "[video]",
        }
    return _clip_text(repr(block))


def _serialize_message(message: Message, depth: int) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        content = message.content
        if isinstance(content, str):
            serialized_content = _clip_text(content)
        else:
            serialized_content = [
                _serialize_content_block(block, depth - 1)
                for block in content[:_MAX_COLLECTION_ITEMS]
            ]
        return {
            "role": "user",
            "timestamp": message.timestamp,
            "content": serialized_content,
        }

    if isinstance(message, AssistantMessage):
        return {
            "role": "assistant",
            "timestamp": message.timestamp,
            "provider": message.provider,
            "model": message.model,
            "stop_reason": str(message.stop_reason),
            "error_message": _clip_text(message.error_message)
            if message.error_message
            else None,
            "usage": serialize_value(message.usage, depth=depth - 1),
            "content": [
                _serialize_content_block(block, depth - 1)
                for block in message.content[:_MAX_COLLECTION_ITEMS]
            ],
        }

    if isinstance(message, ToolResultMessage):
        return {
            "role": "toolResult",
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "is_error": message.is_error,
            "content": [
                _serialize_content_block(block, depth - 1)
                for block in message.content[:_MAX_COLLECTION_ITEMS]
            ],
            "details": serialize_value(message.details, depth=depth - 1),
        }

    return {"type": type(message).__name__, "value": _clip_text(repr(message))}


def serialize_value(value: Any, depth: int = _MAX_DEPTH) -> Any:
    if depth <= 0:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip_text(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Usage):
        return {
            "input_tokens": value.input_tokens,
            "output_tokens": value.output_tokens,
            "cache_read": value.cache_read,
            "cache_write": value.cache_write,
            "total_tokens": value.total_tokens,
        }
    if isinstance(value, (UserMessage, AssistantMessage, ToolResultMessage)):
        return _serialize_message(value, depth)
    if isinstance(value, ToolResult):
        return {
            "is_error": value.is_error,
            "content": [
                _serialize_content_block(block, depth - 1)
                for block in value.content[:_MAX_COLLECTION_ITEMS]
            ],
            "details": serialize_value(value.details, depth=depth - 1),
        }
    if isinstance(value, dict):
        items = list(value.items())[:_MAX_COLLECTION_ITEMS]
        return {str(key): serialize_value(item, depth=depth - 1) for key, item in items}
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:_MAX_COLLECTION_ITEMS]
        return [serialize_value(item, depth=depth - 1) for item in items]
    return _clip_text(repr(value))


def preview_json(value: Any) -> str:
    return json.dumps(serialize_value(value), ensure_ascii=False, sort_keys=True)

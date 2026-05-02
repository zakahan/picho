"""
pi-ai Type Definition

Define the core types required for LLM interaction.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Union
import time

from ..tool import Tool


class StopReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_USE = "toolUse"
    ERROR = "error"
    ABORTED = "aborted"


@dataclass
class TextContent:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ImageBase64Content:
    type: Literal["image_base64"] = "image_base64"
    data: str = ""
    mime_type: str = "image/png"


@dataclass
class ImageUrlContent:
    type: Literal["image_url"] = "image_url"
    url: str = ""


@dataclass
class ImageFileIdContent:
    type: Literal["image_file_id"] = "image_file_id"
    file_id: str = ""


ImageContent = Union[ImageBase64Content, ImageUrlContent, ImageFileIdContent]


@dataclass
class VideoFileIdContent:
    type: Literal["video_file_id"] = "video_file_id"
    file_path: str | None = None
    file_id: str | None = None


VideoContent = Union[VideoFileIdContent]


@dataclass
class ThinkingContent:
    type: Literal["thinking"] = "thinking"
    thinking: str = ""


@dataclass
class ToolCall:
    type: Literal["toolCall"] = "toolCall"
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    _args_str: str = ""


ContentBlock = Union[
    TextContent,
    ImageBase64Content,
    ImageUrlContent,
    ImageFileIdContent,
    VideoFileIdContent,
    ThinkingContent,
    ToolCall,
]

ToolResultContentBlock = Union[
    TextContent,
    ImageBase64Content,
    ImageUrlContent,
    ImageFileIdContent,
    VideoFileIdContent,
    str,
    dict[str, Any],
]


def normalize_content_block(block: Any) -> ContentBlock:
    """Normalize public content block shapes into picho provider dataclasses."""
    if isinstance(
        block,
        (
            TextContent,
            ImageBase64Content,
            ImageUrlContent,
            ImageFileIdContent,
            VideoFileIdContent,
            ThinkingContent,
            ToolCall,
        ),
    ):
        return block

    if isinstance(block, str):
        return TextContent(type="text", text=block)

    if isinstance(block, dict):
        block_type = block.get("type", "text")
        if block_type in {"text", "input_text", "output_text"}:
            return TextContent(type="text", text=str(block.get("text", "")))
        if block_type == "image_base64":
            return ImageBase64Content(
                type="image_base64",
                data=str(block.get("data", "")),
                mime_type=str(block.get("mime_type", "image/png")),
            )
        if block_type in {"image_url", "input_image"}:
            return ImageUrlContent(
                type="image_url",
                url=str(block.get("url") or block.get("image_url") or ""),
            )
        if block_type == "image_file_id":
            return ImageFileIdContent(
                type="image_file_id",
                file_id=str(block.get("file_id", "")),
            )
        if block_type in {"video_file_id", "input_video"}:
            return VideoFileIdContent(
                type="video_file_id",
                file_path=block.get("file_path"),
                file_id=block.get("file_id"),
            )
        if block_type == "thinking":
            return ThinkingContent(
                type="thinking",
                thinking=str(block.get("thinking", "")),
            )
        if block_type == "toolCall":
            return ToolCall(
                type="toolCall",
                id=str(block.get("id", "")),
                name=str(block.get("name", "")),
                arguments=block.get("arguments", {}) or {},
                _args_str=str(block.get("_args_str", "")),
            )

    raise ValueError(f"Unsupported content block: {type(block).__name__}")


def normalize_content_blocks(content: list[Any]) -> list[ContentBlock]:
    return [normalize_content_block(block) for block in content]


def extract_text_content(content: list[Any]) -> str:
    return "\n".join(
        block.text
        for block in normalize_content_blocks(content)
        if isinstance(block, TextContent) and block.text
    )


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class UserMessage:
    role: Literal["user"] = "user"
    content: str | list[ContentBlock] = ""
    timestamp: float = field(default_factory=lambda: time.time() * 1000)


@dataclass
class AssistantMessage:
    role: Literal["assistant"] = "assistant"
    content: list[ContentBlock] = field(default_factory=list)
    api: str = ""
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = StopReason.STOP
    error_message: str | None = None
    timestamp: float = field(default_factory=lambda: time.time() * 1000)


@dataclass
class ToolResultMessage:
    role: Literal["toolResult"] = "toolResult"
    tool_call_id: str = ""
    tool_name: str = ""
    content: list[ToolResultContentBlock] = field(default_factory=list)
    is_error: bool = False
    details: Any = None


Message = Union[UserMessage, AssistantMessage, ToolResultMessage]


@dataclass
class Context:
    instructions: str = ""
    messages: list[Message] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)


ThinkingLevel = Literal["auto", "off", "minimal", "low", "medium", "high", "xhigh"]


@dataclass
class StreamOptions:
    temperature: float | None = None
    max_tokens: int | None = None
    signal: Any = None
    thinking_level: ThinkingLevel = "auto"
    extra_headers: dict[str, str] | None = None
    extra_query: dict[str, str] | None = None
    extra_body: dict[str, Any] | None = None
    timeout: float | None = None

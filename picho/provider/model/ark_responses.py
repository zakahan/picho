"""
Ark Responses API Provider

Supports the Ark Responses API with reasoning support via HTTP.
"""

import asyncio
import json
from typing import Any

from .base import Model
from ..stream import (
    EventStream,
    StreamEvent,
    AssistantMessageEvent,
    AssistantMessageEventType,
)
from ..types import (
    Context,
    UserMessage,
    TextContent,
    ImageBase64Content,
    ImageUrlContent,
    ImageFileIdContent,
    ThinkingContent,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    StreamOptions,
    Usage,
    StopReason,
    Tool,
    ThinkingLevel,
    VideoFileIdContent,
    emit_payload,
    extract_text_content,
    normalize_content_blocks,
)
from ...logger import format_exception, get_logger, log_exception

_log = get_logger(__name__)

default_ark_model = "doubao-seed-2-0-lite-260215"
default_ark_base_url = "https://ark.cn-beijing.volces.com/api/v3"
default_ark_env = "ARK_API_KEY"


def _format_options_info(options: StreamOptions | None) -> str:
    if not options:
        return ""
    parts = []
    if options.thinking_level and options.thinking_level != "auto":
        parts.append(f"thinking={options.thinking_level}")
    if options.temperature is not None:
        parts.append(f"temp={options.temperature}")
    if options.max_tokens is not None:
        parts.append(f"max_tokens={options.max_tokens}")
    return " ".join(parts) if parts else ""


def _map_thinking_level(
    level: ThinkingLevel,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """
    Map ThinkingLevel to Ark API thinking and reasoning parameters.

    Args:
        level: ThinkingLevel value (auto, off, minimal, low, medium, high, xhigh)

    Returns:
        tuple of (thinking_params, reasoning_params), both None if auto
    """
    if level == "auto":
        return None, None
    elif level == "off":
        return {"type": "disabled"}, {"effort": "minimal"}
    elif level == "xhigh":
        return {"type": "enabled"}, {"effort": "high"}
    else:
        return {"type": "enabled"}, {"effort": level}


async def _ensure_video_file_id(block: VideoFileIdContent, **kwargs) -> str:
    if block.file_id:
        return block.file_id
    if not block.file_path:
        raise ValueError("video_file_id content requires file_id or file_path")

    from ...utils.ark.filesapi import upload_and_wait

    block.file_id = await upload_and_wait(
        file_path=block.file_path,
        api_key=kwargs.get("api_key"),
        base_url=kwargs.get("base_url"),
        fps=1,
    )
    return block.file_id


async def to_ark_messages(
    context: Context, input_types: list[str], **kwargs
) -> tuple[list[dict[str, Any]], str]:
    messages = []
    supports_image = "image" in input_types
    supports_video = "video" in input_types

    for msg in context.messages:
        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": msg.content}],
                    }
                )
            else:
                content = []
                for block in msg.content:
                    if isinstance(block, TextContent):
                        content.append({"type": "input_text", "text": block.text})
                    elif supports_image and isinstance(block, ImageBase64Content):
                        content.append(
                            {
                                "type": "input_image",
                                "image_url": f"data:{block.mime_type};base64,{block.data}",
                            }
                        )
                    elif supports_image and isinstance(block, ImageUrlContent):
                        content.append(
                            {
                                "type": "input_image",
                                "image_url": block.url,
                            }
                        )
                    elif supports_image and isinstance(block, ImageFileIdContent):
                        content.append(
                            {
                                "type": "input_image",
                                "file_id": block.file_id,
                            }
                        )
                    elif supports_video and isinstance(block, VideoFileIdContent):
                        content.append(
                            {
                                "type": "input_video",
                                "file_id": await _ensure_video_file_id(block, **kwargs),
                            }
                        )
                if content:
                    messages.append({"role": "user", "content": content})

        elif isinstance(msg, AssistantMessage):
            has_content = False
            for block in msg.content:
                if isinstance(block, TextContent):
                    if block.text:
                        messages.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": block.text}
                                ],
                                "status": "completed",
                            }
                        )
                        has_content = True
                elif isinstance(block, ThinkingContent):
                    messages.append(
                        {
                            "type": "reasoning",
                            "summary": [
                                {"type": "summary_text", "text": block.thinking}
                            ],
                        }
                    )
                    has_content = True
                elif isinstance(block, ToolCall):
                    messages.append(
                        {
                            "type": "function_call",
                            "call_id": block.id,
                            "name": block.name,
                            "arguments": json.dumps(block.arguments),
                        }
                    )
                    has_content = True
            if not has_content and msg.error_message:
                messages.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": f"[Error: {msg.error_message}]",
                            }
                        ],
                        "status": "completed",
                    }
                )

        elif isinstance(msg, ToolResultMessage):
            content = normalize_content_blocks(msg.content)
            text_result = extract_text_content(content)
            has_videos = any(isinstance(c, VideoFileIdContent) for c in content)
            has_images = any(
                isinstance(c, (ImageBase64Content, ImageUrlContent, ImageFileIdContent))
                for c in content
            )
            has_text = len(text_result) > 0
            call_id = (
                msg.tool_call_id.split("|")[0]
                if "|" in msg.tool_call_id
                else msg.tool_call_id
            )

            messages.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": text_result if has_text else "(see attached image)",
                }
            )

            if has_images and supports_image:
                image_blocks = []
                for block in content:
                    if isinstance(block, ImageBase64Content):
                        image_blocks.append(
                            {
                                "type": "input_image",
                                "image_url": f"data:{block.mime_type};base64,{block.data}",
                            }
                        )
                    elif isinstance(block, ImageUrlContent):
                        image_blocks.append(
                            {
                                "type": "input_image",
                                "image_url": block.url,
                            }
                        )
                    elif isinstance(block, ImageFileIdContent):
                        image_blocks.append(
                            {
                                "type": "input_image",
                                "file_id": block.file_id,
                            }
                        )
                if image_blocks:
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Attached image(s) from tool result:",
                                },
                                *image_blocks,
                            ],
                        }
                    )

            if has_videos and supports_video:
                video_blocks = []
                for block in content:
                    if isinstance(block, VideoFileIdContent):
                        video_blocks.append(
                            {
                                "type": "input_video",
                                "file_id": await _ensure_video_file_id(block, **kwargs),
                            }
                        )
                if video_blocks:
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Attached video(s) from tool result:",
                                },
                                *video_blocks,
                            ],
                        }
                    )

    instructions = context.instructions

    return messages, instructions


def _convert_ark_responses_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": {
                "type": t.parameters.type,
                "properties": t.parameters.properties,
                "required": t.parameters.required,
            },
        }
        for t in tools
    ]


def _map_stop_reason(status: str | None) -> StopReason:
    if not status:
        return StopReason.STOP
    mapping = {
        "completed": StopReason.STOP,
        "incomplete": StopReason.LENGTH,
        "failed": StopReason.ERROR,
        "cancelled": StopReason.ERROR,
        "in_progress": StopReason.STOP,
        "queued": StopReason.STOP,
    }
    return mapping.get(status, StopReason.STOP)


class ArkResponsesModel(Model):
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        api_key = self.require_api_key()
        messages, instructions = await to_ark_messages(
            context, self.input_types, api_key=api_key, base_url=self.base_url
        )

        tools = None
        if context.tools:
            tools = _convert_ark_responses_tools(context.tools)

        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def run_stream():
            options_info = _format_options_info(options)
            _log.debug(
                f"Ark Responses stream start: model={self.model_name} messages={len(messages)} tools={len(tools or [])} {options_info}"
            )
            import httpx

            try:
                params: dict[str, Any] = {
                    "model": self.model_name,
                    "input": messages,
                    "stream": True,
                }

                if instructions:
                    params["instructions"] = instructions

                if tools:
                    params["tools"] = tools

                if options:
                    if options.temperature is not None:
                        params["temperature"] = options.temperature
                    if options.max_tokens is not None:
                        params["max_output_tokens"] = options.max_tokens
                    if options.extra_headers is not None:
                        params["extra_headers"] = options.extra_headers
                    if options.extra_query is not None:
                        params["extra_query"] = options.extra_query
                    if options.extra_body is not None:
                        params["extra_body"] = options.extra_body
                    if options.timeout is not None:
                        params["timeout"] = options.timeout

                    if options.thinking_level and options.thinking_level != "auto":
                        thinking_params, reasoning_params = _map_thinking_level(
                            options.thinking_level
                        )
                        if thinking_params:
                            params["thinking"] = thinking_params
                        if reasoning_params:
                            params["reasoning"] = reasoning_params

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                }

                extra_headers: dict | None = params.pop("extra_headers", None)
                if extra_headers:
                    headers.update(extra_headers)

                extra_query: dict | None = params.pop("extra_query", None)
                if extra_query:
                    params.update(extra_query)

                extra_body: dict | None = params.pop("extra_body", None)
                if extra_body:
                    params.update(extra_body)

                timeout = params.pop("timeout", 60.0)

                url = f"{self.base_url.rstrip('/')}/responses"

                await emit_payload(options, params, self)

                content_blocks: list[Any] = []
                current_item_id: str | None = None
                usage = Usage()
                stop_reason = StopReason.STOP

                stream.push(StreamEvent(type="message_start"))

                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", url, json=params, headers=headers
                    ) as response:
                        if response.status_code >= 400:
                            error_body = await response.aread()
                            error_text = error_body.decode("utf-8", errors="replace")
                            raise Exception(
                                f"HTTP {response.status_code}: {error_text}"
                            )

                        buffer = ""
                        async for chunk in response.aiter_text():
                            if options and options.signal and options.signal.is_set():
                                stop_reason = StopReason.ABORTED
                                break

                            buffer += chunk

                            while "\n\n" in buffer:
                                event_data, buffer = buffer.split("\n\n", 1)

                                data_str = None
                                for line in event_data.split("\n"):
                                    if line.startswith("data: "):
                                        data_str = line[6:]

                                if data_str is None:
                                    continue

                                if data_str.strip() == "[DONE]":
                                    continue

                                try:
                                    event = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue

                                event_type = event.get("type")

                                if event_type == "response.output_item.added":
                                    item = event.get("item", {})
                                    item_type = item.get("type")
                                    item_id = item.get("id", "")
                                    current_item_id = item_id
                                    if item_type == "reasoning":
                                        content_blocks.append(
                                            ThinkingContent(
                                                type="thinking", thinking=""
                                            )
                                        )
                                    elif item_type == "message":
                                        content_blocks.append(
                                            TextContent(type="text", text="")
                                        )
                                    elif item_type == "function_call":
                                        content_blocks.append(
                                            ToolCall(
                                                type="toolCall",
                                                id=f"{item.get('call_id', '')}|{item_id}",
                                                name=item.get("name", ""),
                                                arguments={},
                                                _args_str=item.get("arguments", ""),
                                            )
                                        )
                                        stream.push(
                                            StreamEvent(
                                                type="tool_call_start",
                                                data=AssistantMessageEvent(
                                                    type=AssistantMessageEventType.TOOL_CALL_START,
                                                    tool_call_id=item.get(
                                                        "call_id", ""
                                                    ),
                                                    tool_name=item.get("name", ""),
                                                ),
                                            )
                                        )

                                elif (
                                    event_type
                                    == "response.reasoning_summary_text.delta"
                                ):
                                    delta = event.get("delta", "")
                                    item_id = event.get("item_id", current_item_id)
                                    for block in content_blocks:
                                        if isinstance(block, ThinkingContent):
                                            block.thinking += delta
                                            break
                                    stream.push(
                                        StreamEvent(
                                            type="thinking_delta",
                                            data=AssistantMessageEvent(
                                                type=AssistantMessageEventType.THINKING_DELTA,
                                                delta=delta,
                                            ),
                                        )
                                    )

                                elif event_type == "response.output_text.delta":
                                    delta = event.get("delta", "")
                                    item_id = event.get("item_id", current_item_id)
                                    for block in content_blocks:
                                        if isinstance(block, TextContent):
                                            block.text += delta
                                            break
                                    stream.push(
                                        StreamEvent(
                                            type="content_delta",
                                            data=AssistantMessageEvent(
                                                type=AssistantMessageEventType.TEXT_DELTA,
                                                delta=delta,
                                            ),
                                        )
                                    )

                                elif (
                                    event_type
                                    == "response.function_call_arguments.delta"
                                ):
                                    delta = event.get("delta", "")
                                    item_id = event.get("item_id", current_item_id)
                                    for block in content_blocks:
                                        if (
                                            isinstance(block, ToolCall)
                                            and item_id
                                            and item_id in block.id
                                        ):
                                            block._args_str = (
                                                getattr(block, "_args_str", "") + delta
                                            )
                                            stream.push(
                                                StreamEvent(
                                                    type="tool_call_delta",
                                                    data=AssistantMessageEvent(
                                                        type=AssistantMessageEventType.TOOL_CALL_DELTA,
                                                        tool_call_id=block.id,
                                                        delta=delta,
                                                    ),
                                                )
                                            )
                                            break

                                elif event_type == "response.output_item.done":
                                    item = event.get("item", {})
                                    if item.get("type") == "function_call":
                                        item_id = item.get("id", "")
                                        for block in content_blocks:
                                            if (
                                                isinstance(block, ToolCall)
                                                and item_id
                                                and item_id in block.id
                                            ):
                                                args_str = getattr(
                                                    block, "_args_str", "{}"
                                                )
                                                try:
                                                    block.arguments = (
                                                        json.loads(args_str)
                                                        if args_str
                                                        else {}
                                                    )
                                                except Exception as e:  # noqa
                                                    block.arguments = {}
                                                break

                                elif event_type == "response.completed":
                                    resp = event.get("response", {})
                                    resp_usage = resp.get("usage", {})
                                    if resp_usage:
                                        input_details = resp_usage.get(
                                            "input_tokens_details", {}
                                        )
                                        cached_tokens = input_details.get(
                                            "cached_tokens", 0
                                        )
                                        usage = Usage(
                                            input_tokens=(
                                                resp_usage.get("input_tokens", 0)
                                                - cached_tokens
                                            ),
                                            output_tokens=resp_usage.get(
                                                "output_tokens", 0
                                            ),
                                            cache_read=cached_tokens,
                                            cache_write=0,
                                        )
                                    resp_status = resp.get("status")
                                    if resp_status:
                                        stop_reason = _map_stop_reason(resp_status)

                                elif event_type == "error":
                                    error_msg = (
                                        event.get("message")
                                        or event.get("error")
                                        or json.dumps(event, ensure_ascii=False)
                                    )
                                    raise Exception(f"Responses API error: {error_msg}")

                                elif event_type == "response.failed":
                                    resp = event.get("response", {})
                                    error = resp.get("error", {})
                                    if error:
                                        error_code = error.get("code", "Unknown")
                                        error_message = error.get(
                                            "message", "Unknown error"
                                        )
                                        raise Exception(
                                            f"Responses API failed [{error_code}]: {error_message}"
                                        )
                                    raise Exception("Response failed")

                has_tool_calls = any(isinstance(b, ToolCall) for b in content_blocks)
                if has_tool_calls and stop_reason == StopReason.STOP:
                    stop_reason = StopReason.TOOL_USE

                message = AssistantMessage(
                    role="assistant",
                    content=content_blocks,
                    api="ark-responses",
                    provider="ark",
                    model=self.model_name,
                    usage=usage,
                    stop_reason=stop_reason,
                )

                _log.info(
                    f"Model response | stop={stop_reason.value} in={usage.input_tokens} out={usage.output_tokens}"
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)

            except Exception as e:
                error_detail = format_exception(e)
                log_exception(
                    _log, "Ark Responses stream error", e, model=self.model_name
                )
                message = AssistantMessage(
                    role="assistant",
                    content=[TextContent(type="text", text="")],
                    api="ark-responses",
                    provider="ark",
                    model=self.model_name,
                    usage=Usage(),
                    stop_reason=StopReason.ERROR,
                    error_message=error_detail,
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.set_error(e)

        asyncio.create_task(run_stream())
        return stream

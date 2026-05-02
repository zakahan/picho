"""
OpenAI Responses API Provider

Supports the new OpenAI Responses API with reasoning support.
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
    ThinkingContent,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    StreamOptions,
    Usage,
    StopReason,
    Tool,
    ThinkingLevel,
    extract_text_content,
    normalize_content_blocks,
)
from ...logger import get_logger

_log = get_logger(__name__)

default_openai_model = "gpt-4o"
default_openai_base_url = "https://api.openai.com/v1"
default_openai_env = "OPENAI_API_KEY"


def clamp_reasoning(effort: ThinkingLevel | None) -> ThinkingLevel | None:
    if effort is None or effort in ("off", "auto"):
        return None
    if effort == "xhigh":
        return "high"
    return effort


def to_openai_messages(
    context: Context, input_types: list[str]
) -> tuple[list[dict[str, Any]], str]:
    messages = []
    supports_image = "image" in input_types

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
                    elif supports_image:
                        if isinstance(block, ImageBase64Content):
                            content.append(
                                {
                                    "type": "input_image",
                                    "image_url": f"data:{block.mime_type};base64,{block.data}",
                                }
                            )
                        elif isinstance(block, ImageUrlContent):
                            content.append(
                                {
                                    "type": "input_image",
                                    "image_url": block.url,
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
            has_images = any(
                isinstance(c, (ImageBase64Content, ImageUrlContent)) for c in content
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

    instructions = context.instructions

    return messages, instructions


def _convert_openai_responses_tools(tools: list[Tool]) -> list[dict[str, Any]]:
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


class OpenAIResponsesModel(Model):
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.require_api_key(), base_url=self.base_url)

        messages, instructions = to_openai_messages(context, self.input_types)

        tools = None
        if context.tools:
            tools = _convert_openai_responses_tools(context.tools)

        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def run_stream():
            _log.info(
                f"OpenAI Responses stream start: model={self.model_name} messages={len(messages)} tools={len(tools or [])}"
            )
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

                    if options.thinking_level:
                        reasoning_effort = clamp_reasoning(options.thinking_level)
                        if reasoning_effort:
                            params["reasoning"] = {
                                "effort": reasoning_effort,
                                "summary": "auto",
                            }
                            params["include"] = ["reasoning.encrypted_content"]

                response = await client.responses.create(**params)

                content_blocks: list[Any] = []
                current_item: dict[str, Any] | None = None
                usage = Usage()
                stop_reason = StopReason.STOP

                stream.push(StreamEvent(type="message_start"))

                async for event in response:
                    if options and options.signal and options.signal.is_set():
                        stop_reason = StopReason.ABORTED
                        break

                    event_type = event.type if hasattr(event, "type") else None

                    if event_type == "response.output_item.added":
                        item = event.item
                        if item.type == "reasoning":
                            current_item = item
                            content_blocks.append(
                                ThinkingContent(type="thinking", thinking="")
                            )
                        elif item.type == "message":
                            current_item = item
                            content_blocks.append(TextContent(type="text", text=""))
                        elif item.type == "function_call":
                            current_item = item
                            content_blocks.append(
                                ToolCall(
                                    type="toolCall",
                                    id=f"{item.call_id}|{item.id}",
                                    name=item.name,
                                    arguments={},
                                    _args_str=item.arguments or "",
                                )
                            )
                            stream.push(
                                StreamEvent(
                                    type="tool_call_start",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TOOL_CALL_START,
                                        tool_call_id=item.call_id,
                                        tool_name=item.name,
                                    ),
                                )
                            )

                    elif event_type == "response.reasoning_summary_text.delta":
                        if current_item and current_item.type == "reasoning":
                            delta = event.delta
                            if content_blocks and isinstance(
                                content_blocks[-1], ThinkingContent
                            ):
                                content_blocks[-1].thinking += delta
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
                        if current_item and current_item.type == "message":
                            delta = event.delta
                            if content_blocks and isinstance(
                                content_blocks[-1], TextContent
                            ):
                                content_blocks[-1].text += delta
                                stream.push(
                                    StreamEvent(
                                        type="content_delta",
                                        data=AssistantMessageEvent(
                                            type=AssistantMessageEventType.TEXT_DELTA,
                                            delta=delta,
                                        ),
                                    )
                                )

                    elif event_type == "response.function_call_arguments.delta":
                        if current_item and current_item.type == "function_call":
                            delta = event.delta
                            if content_blocks and isinstance(
                                content_blocks[-1], ToolCall
                            ):
                                content_blocks[-1]._args_str = (
                                    getattr(content_blocks[-1], "_args_str", "") + delta
                                )
                                stream.push(
                                    StreamEvent(
                                        type="tool_call_delta",
                                        data=AssistantMessageEvent(
                                            type=AssistantMessageEventType.TOOL_CALL_DELTA,
                                            tool_call_id=content_blocks[-1].id,
                                            delta=delta,
                                        ),
                                    )
                                )

                    elif event_type == "response.output_item.done":
                        item = event.item
                        if item.type == "function_call":
                            if content_blocks and isinstance(
                                content_blocks[-1], ToolCall
                            ):
                                args_str = getattr(
                                    content_blocks[-1], "_args_str", "{}"
                                )
                                try:
                                    content_blocks[-1].arguments = (
                                        json.loads(args_str) if args_str else {}
                                    )
                                except Exception as e:  # noqa
                                    content_blocks[-1].arguments = {}

                    elif event_type == "response.completed":
                        resp = event.response
                        if resp and hasattr(resp, "usage") and resp.usage:
                            cached_tokens = (
                                getattr(
                                    resp.usage.input_tokens_details, "cached_tokens", 0
                                )
                                if hasattr(resp.usage, "input_tokens_details")
                                else 0
                            )
                            usage = Usage(
                                input_tokens=(resp.usage.input_tokens or 0)
                                - cached_tokens,
                                output_tokens=resp.usage.output_tokens or 0,
                                cache_read=cached_tokens,
                                cache_write=0,
                            )
                        if resp and hasattr(resp, "status"):
                            stop_reason = _map_stop_reason(resp.status)

                    elif event_type == "error":
                        error_msg = (
                            f"Error: {event.message}"
                            if hasattr(event, "message")
                            else "Unknown error"
                        )
                        raise Exception(error_msg)

                    elif event_type == "response.failed":
                        error = (
                            getattr(event.response, "error", None)
                            if hasattr(event, "response")
                            else None
                        )
                        if error:
                            raise Exception(f"{error.code}: {error.message}")
                        raise Exception("Response failed")

                has_tool_calls = any(isinstance(b, ToolCall) for b in content_blocks)
                if has_tool_calls and stop_reason == StopReason.STOP:
                    stop_reason = StopReason.TOOL_USE

                message = AssistantMessage(
                    role="assistant",
                    content=content_blocks,
                    api="openai-responses",
                    provider=self.model_provider,
                    model=self.model_name,
                    usage=usage,
                    stop_reason=stop_reason,
                )

                _log.info(
                    f"OpenAI Responses stream end: stop_reason={stop_reason} usage_input={usage.input_tokens} usage_output={usage.output_tokens}"
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)

            except Exception as e:
                _log.error(f"OpenAI Responses stream error: {e}")
                message = AssistantMessage(
                    role="assistant",
                    content=[TextContent(type="text", text=f"Error: {str(e)}")],
                    api="openai-responses",
                    provider=self.model_provider,
                    model=self.model_name,
                    stop_reason=StopReason.ERROR,
                    error_message=str(e),
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)

        asyncio.create_task(run_stream())
        return stream

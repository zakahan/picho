"""
OpenAI Completion API Provider

Supports chat completion API with reasoning_effort for thinking models.
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
    ThinkingLevel,
)
from ...tool import Tool
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
) -> list[dict[str, Any]]:
    messages = []
    supports_image = "image" in input_types

    if context.instructions:
        messages.append({"role": "system", "content": context.instructions})

    for msg in context.messages:
        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                messages.append({"role": "user", "content": msg.content})
            else:
                content = []
                for block in msg.content:
                    if isinstance(block, TextContent):
                        content.append({"type": "text", "text": block.text})
                    elif supports_image:
                        if isinstance(block, ImageBase64Content):
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{block.mime_type};base64,{block.data}"
                                    },
                                }
                            )
                        elif isinstance(block, ImageUrlContent):
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": block.url},
                                }
                            )
                if content:
                    messages.append({"role": "user", "content": content})

        elif isinstance(msg, AssistantMessage):
            content = []
            for block in msg.content:
                if isinstance(block, TextContent):
                    if block.text:
                        content.append({"type": "text", "text": block.text})
                elif isinstance(block, ThinkingContent):
                    if block.thinking.strip():
                        content.append(
                            {
                                "type": "thinking",
                                "thinking": block.thinking,
                            }
                        )
                elif isinstance(block, ToolCall):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.arguments),
                            },
                        }
                    )
            if content:
                messages.append({"role": "assistant", "content": content})
            elif msg.error_message:
                messages.append(
                    {"role": "assistant", "content": f"[Error: {msg.error_message}]"}
                )

        elif isinstance(msg, ToolResultMessage):
            text_result = "\n".join(
                c.text for c in msg.content if isinstance(c, TextContent)
            )
            has_images = any(
                isinstance(c, (ImageBase64Content, ImageUrlContent))
                for c in msg.content
            )
            has_text = bool(text_result.strip())

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": text_result if has_text else "(see attached image)",
                }
            )

            if has_images and supports_image:
                image_blocks = []
                for block in msg.content:
                    if isinstance(block, ImageBase64Content):
                        image_blocks.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{block.mime_type};base64,{block.data}"
                                },
                            }
                        )
                    elif isinstance(block, ImageUrlContent):
                        image_blocks.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": block.url},
                            }
                        )
                if image_blocks:
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Attached image(s) from tool result:",
                                },
                                *image_blocks,
                            ],
                        }
                    )

    return messages


def _convert_openai_completion_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": t.parameters.type,
                    "properties": t.parameters.properties,
                    "required": t.parameters.required,
                }
                if t.parameters
                else {},
            },
        }
        for t in tools
    ]


class OpenAICompletionModel(Model):
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        from openai import AsyncOpenAI
        from openai.types import CompletionUsage

        client = AsyncOpenAI(api_key=self.require_api_key(), base_url=self.base_url)

        messages = to_openai_messages(context, self.input_types)

        tools = None
        if context.tools:
            tools = _convert_openai_completion_tools(context.tools)

        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def run_stream():
            _log.info(
                f"OpenAI stream start: model={self.model_name} messages={len(messages)} tools={len(tools or [])}"
            )
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model_name,
                    "messages": messages,
                    "tools": tools,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }

                if options:
                    if options.temperature is not None:
                        kwargs["temperature"] = options.temperature
                    if options.max_tokens is not None:
                        kwargs["max_tokens"] = options.max_tokens
                    if options.extra_headers is not None:
                        kwargs["extra_headers"] = options.extra_headers
                    if options.extra_query is not None:
                        kwargs["extra_query"] = options.extra_query
                    if options.extra_body is not None:
                        kwargs["extra_body"] = options.extra_body
                    if options.timeout is not None:
                        kwargs["timeout"] = options.timeout

                    if options.thinking_level:
                        reasoning_effort = clamp_reasoning(options.thinking_level)
                        if reasoning_effort:
                            kwargs["reasoning_effort"] = reasoning_effort

                response = await client.chat.completions.create(**kwargs)

                content_blocks: list[Any] = []
                current_text = ""
                current_thinking = ""
                current_tool_calls: dict[int, ToolCall] = {}
                usage = Usage()
                stop_reason = StopReason.STOP

                stream.push(StreamEvent(type="message_start"))

                async for chunk in response:
                    if options and options.signal and options.signal.is_set():
                        stop_reason = StopReason.ABORTED
                        break

                    delta = chunk.choices[0].delta if chunk.choices else None

                    if delta:
                        if delta.content:
                            current_text += delta.content
                            stream.push(
                                StreamEvent(
                                    type="content_delta",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TEXT_DELTA,
                                        delta=delta.content,
                                    ),
                                )
                            )

                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in current_tool_calls:
                                    current_tool_calls[idx] = ToolCall(
                                        type="toolCall",
                                        id=tc.id or "",
                                        name=tc.function.name if tc.function else "",
                                        arguments={},
                                        _args_str="",
                                    )
                                    stream.push(
                                        StreamEvent(
                                            type="tool_call_start",
                                            data=AssistantMessageEvent(
                                                type=AssistantMessageEventType.TOOL_CALL_START,
                                                tool_call_id=tc.id or "",
                                                tool_name=tc.function.name
                                                if tc.function
                                                else "",
                                            ),
                                        )
                                    )

                                if tc.function and tc.function.arguments:
                                    current_tool_calls[
                                        idx
                                    ]._args_str += tc.function.arguments
                                    stream.push(
                                        StreamEvent(
                                            type="tool_call_delta",
                                            data=AssistantMessageEvent(
                                                type=AssistantMessageEventType.TOOL_CALL_DELTA,
                                                tool_call_id=current_tool_calls[idx].id,
                                                delta=tc.function.arguments,
                                            ),
                                        )
                                    )

                        reasoning_fields = [
                            "reasoning_content",
                            "reasoning",
                            "reasoning_text",
                        ]
                        for field in reasoning_fields:
                            reasoning_content = getattr(delta, field, None)
                            if reasoning_content:
                                current_thinking += reasoning_content
                                stream.push(
                                    StreamEvent(
                                        type="thinking_delta",
                                        data=AssistantMessageEvent(
                                            type=AssistantMessageEventType.THINKING_DELTA,
                                            delta=reasoning_content,
                                        ),
                                    )
                                )
                                break

                    if chunk.usage and isinstance(chunk.usage, CompletionUsage):
                        usage = Usage(
                            input_tokens=chunk.usage.prompt_tokens or 0,
                            output_tokens=chunk.usage.completion_tokens or 0,
                        )

                    finish_reason = (
                        chunk.choices[0].finish_reason if chunk.choices else None
                    )
                    if finish_reason:
                        if finish_reason == "tool_calls":
                            stop_reason = StopReason.TOOL_USE
                        elif finish_reason == "length":
                            stop_reason = StopReason.LENGTH

                if current_thinking:
                    content_blocks.append(
                        ThinkingContent(
                            type="thinking",
                            thinking=current_thinking,
                        )
                    )

                if current_text:
                    content_blocks.append(TextContent(type="text", text=current_text))

                for idx in sorted(current_tool_calls.keys()):
                    tc = current_tool_calls[idx]
                    if tc.id and tc.name:
                        try:
                            args_str = getattr(tc, "_args_str", "{}")
                            tc.arguments = json.loads(args_str) if args_str else {}
                        except Exception as e:  # noqa
                            tc.arguments = {}
                        content_blocks.append(tc)

                message = AssistantMessage(
                    role="assistant",
                    content=content_blocks,
                    api="openai-completions",
                    provider="openai",
                    model=self.model_name,
                    usage=usage,
                    stop_reason=stop_reason,
                )

                _log.info(
                    f"OpenAI stream end: stop_reason={stop_reason} usage_input={usage.input_tokens} usage_output={usage.output_tokens}"
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)

            except Exception as e:
                _log.error(f"OpenAI stream error: {e}")
                message = AssistantMessage(
                    role="assistant",
                    content=[TextContent(type="text", text=f"Error: {str(e)}")],
                    api="openai-completions",
                    provider="openai",
                    model=self.model_name,
                    stop_reason=StopReason.ERROR,
                    error_message=str(e),
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)

        asyncio.create_task(run_stream())
        return stream

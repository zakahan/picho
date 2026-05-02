"""
Google Gemini Provider

Supports Gemini streaming with text, images, tool use, and thinking output.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
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

default_google_model = "gemini-3-flash-preview"
default_google_base_url = "https://generativelanguage.googleapis.com/v1beta"
default_google_env = "GEMINI_API_KEY"

_tool_call_counter = itertools.count(1)


def _get_value(obj: Any, *names: str) -> Any:
    for name in names:
        if obj is None:
            return None
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _map_stop_reason(reason: Any) -> StopReason:
    reason_text = str(reason).split(".", 1)[-1].lower() if reason is not None else ""
    if reason_text in ("", "stop", "finish_reason_unspecified"):
        return StopReason.STOP
    if reason_text == "max_tokens":
        return StopReason.LENGTH
    if reason_text in ("malformed_function_call", "unexpected_tool_call"):
        return StopReason.ERROR
    if any(
        token in reason_text for token in ("safety", "blocklist", "prohibited", "spi")
    ):
        return StopReason.ERROR
    return StopReason.STOP


def _google_thinking_config(options: StreamOptions, types_module: Any) -> Any:
    if options.thinking_level == "off":
        return types_module.ThinkingConfig(thinkingBudget=0)
    if options.thinking_level == "auto":
        return None

    thinking_level_map = {
        "minimal": types_module.ThinkingLevel.MINIMAL,
        "low": types_module.ThinkingLevel.LOW,
        "medium": types_module.ThinkingLevel.MEDIUM,
        "high": types_module.ThinkingLevel.HIGH,
        "xhigh": types_module.ThinkingLevel.HIGH,
    }
    return types_module.ThinkingConfig(
        includeThoughts=True,
        thinkingLevel=thinking_level_map.get(
            options.thinking_level, types_module.ThinkingLevel.MEDIUM
        ),
    )


def _convert_google_tools(tools: list[Tool], types_module: Any) -> list[Any]:
    function_declarations = []
    for tool in tools:
        schema = (
            {
                "type": tool.parameters.type,
                "properties": tool.parameters.properties,
                "required": tool.parameters.required,
            }
            if tool.parameters
            else {"type": "object", "properties": {}, "required": []}
        )
        function_declarations.append(
            types_module.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parametersJsonSchema=schema,
            )
        )
    return [types_module.Tool(functionDeclarations=function_declarations)]


def _make_google_parts(
    blocks: str | list[Any], input_types: list[str], types_module: Any
) -> list[Any]:
    supports_image = "image" in input_types
    if isinstance(blocks, str):
        return [types_module.Part.from_text(text=blocks)] if blocks.strip() else []

    parts: list[Any] = []
    for block in normalize_content_blocks(blocks):
        if isinstance(block, TextContent) and block.text:
            parts.append(types_module.Part.from_text(text=block.text))
        elif supports_image and isinstance(block, ImageBase64Content):
            parts.append(
                types_module.Part.from_bytes(
                    data=base64.b64decode(block.data),
                    mime_type=block.mime_type,
                )
            )
        elif supports_image and isinstance(block, ImageUrlContent):
            parts.append(
                types_module.Part.from_uri(
                    file_uri=block.url,
                    mime_type=None,
                )
            )
    return parts


def to_google_messages(
    context: Context, input_types: list[str], types_module: Any
) -> list[Any]:
    messages: list[Any] = []

    for msg in context.messages:
        if isinstance(msg, UserMessage):
            parts = _make_google_parts(msg.content, input_types, types_module)
            if parts:
                messages.append(types_module.Content(role="user", parts=parts))

        elif isinstance(msg, AssistantMessage):
            parts: list[Any] = []
            for block in msg.content:
                if isinstance(block, TextContent) and block.text:
                    parts.append(types_module.Part.from_text(text=block.text))
                elif isinstance(block, ThinkingContent) and block.thinking.strip():
                    # Gemini history does not accept picho thinking blocks as-is.
                    parts.append(types_module.Part.from_text(text=block.thinking))
                elif isinstance(block, ToolCall):
                    parts.append(
                        types_module.Part.from_function_call(
                            name=block.name,
                            args=block.arguments,
                        )
                    )
            if parts:
                messages.append(types_module.Content(role="model", parts=parts))

        elif isinstance(msg, ToolResultMessage):
            content = normalize_content_blocks(msg.content)
            response_payload = {
                "content": extract_text_content(content),
                "is_error": msg.is_error,
            }
            tool_name = msg.tool_name or _tool_result_name(msg.tool_call_id)
            messages.append(
                types_module.Content(
                    role="tool",
                    parts=[
                        types_module.Part.from_function_response(
                            name=tool_name,
                            response=response_payload,
                        )
                    ],
                )
            )

            extra_parts = [
                part
                for part in _make_google_parts(content, input_types, types_module)
                if _get_value(part, "inline_data", "inlineData")
                or _get_value(part, "file_data", "fileData")
            ]
            if extra_parts:
                messages.append(
                    types_module.Content(
                        role="user",
                        parts=[
                            types_module.Part.from_text(
                                text="Attached media from tool result:"
                            ),
                            *extra_parts,
                        ],
                    )
                )

    return messages


def _tool_result_name(tool_call_id: str) -> str:
    if "|" in tool_call_id:
        return tool_call_id.split("|", 1)[0]
    return tool_call_id or "tool"


class GoogleModel(Model):
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise ImportError(
                "Google provider requires optional dependency `google-genai`. "
                "Install it with `uv add picho[provider-google]`."
            ) from error

        http_options = None
        extra_headers = options.extra_headers if options else None
        timeout = (
            int(options.timeout) if options and options.timeout is not None else None
        )
        extra_body = options.extra_body if options else None
        if self.base_url or extra_headers or timeout is not None or extra_body:
            http_options = types.HttpOptions(
                baseUrl=self.base_url,
                apiVersion="",
                headers=extra_headers,
                timeout=timeout,
                extraBody=extra_body,
            )

        client = genai.Client(api_key=self.require_api_key(), http_options=http_options)
        messages = to_google_messages(context, self.input_types, types)
        google_tools = (
            _convert_google_tools(context.tools, types) if context.tools else None
        )

        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def run_stream() -> None:
            _log.info(
                "Google stream start: model=%s messages=%s tools=%s",
                self.model_name,
                len(messages),
                len(context.tools),
            )
            usage = Usage()
            content_blocks: list[Any] = []
            current_block: TextContent | ThinkingContent | None = None
            stop_reason = StopReason.STOP

            try:
                config = types.GenerateContentConfig(
                    systemInstruction=context.instructions or None,
                    temperature=options.temperature if options else None,
                    maxOutputTokens=options.max_tokens if options else None,
                    tools=google_tools,
                    thinkingConfig=(
                        _google_thinking_config(options, types) if options else None
                    ),
                )
                if google_tools:
                    config.toolConfig = types.ToolConfig(
                        functionCallingConfig=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.AUTO,
                            streamFunctionCallArguments=True,
                        )
                    )

                response = client.aio.models.generate_content_stream(
                    model=self.model_name,
                    contents=messages,
                    config=config,
                )

                stream.push(StreamEvent(type="message_start"))

                async for chunk in response:
                    if options and options.signal and options.signal.is_set():
                        stop_reason = StopReason.ABORTED
                        break

                    response_id = _get_value(chunk, "response_id", "responseId")
                    if response_id:
                        pass

                    candidates = _get_value(chunk, "candidates") or []
                    candidate = candidates[0] if candidates else None
                    content = _get_value(candidate, "content")
                    parts = _get_value(content, "parts") or []

                    for part in parts:
                        text = _get_value(part, "text")
                        if text:
                            is_thinking = bool(
                                _get_value(part, "thought")
                                or _get_value(part, "thoughtSignature")
                            )
                            if is_thinking:
                                if not isinstance(current_block, ThinkingContent):
                                    current_block = ThinkingContent(
                                        type="thinking", thinking=""
                                    )
                                    content_blocks.append(current_block)
                                current_block.thinking += text
                                stream.push(
                                    StreamEvent(
                                        type="thinking_delta",
                                        data=AssistantMessageEvent(
                                            type=AssistantMessageEventType.THINKING_DELTA,
                                            delta=text,
                                        ),
                                    )
                                )
                            else:
                                if not isinstance(current_block, TextContent):
                                    current_block = TextContent(type="text", text="")
                                    content_blocks.append(current_block)
                                current_block.text += text
                                stream.push(
                                    StreamEvent(
                                        type="content_delta",
                                        data=AssistantMessageEvent(
                                            type=AssistantMessageEventType.TEXT_DELTA,
                                            delta=text,
                                        ),
                                    )
                                )

                        function_call = _get_value(
                            part, "function_call", "functionCall"
                        )
                        if function_call:
                            current_block = None
                            tool_name = _get_value(function_call, "name") or ""
                            tool_args = _get_value(function_call, "args") or {}
                            tool_id = (
                                _get_value(function_call, "id")
                                or f"{tool_name}_{next(_tool_call_counter)}"
                            )
                            tool_call = ToolCall(
                                type="toolCall",
                                id=tool_id,
                                name=tool_name,
                                arguments=tool_args,
                                _args_str=json.dumps(tool_args, ensure_ascii=False),
                            )
                            content_blocks.append(tool_call)
                            stream.push(
                                StreamEvent(
                                    type="tool_call_start",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TOOL_CALL_START,
                                        tool_call_id=tool_call.id,
                                        tool_name=tool_name,
                                    ),
                                )
                            )
                            stream.push(
                                StreamEvent(
                                    type="tool_call_delta",
                                    data=AssistantMessageEvent(
                                        type=AssistantMessageEventType.TOOL_CALL_DELTA,
                                        tool_call_id=tool_call.id,
                                        delta=tool_call._args_str,
                                    ),
                                )
                            )

                    finish_reason = _get_value(
                        candidate, "finish_reason", "finishReason"
                    )
                    if finish_reason:
                        stop_reason = _map_stop_reason(finish_reason)

                    usage_meta = _get_value(chunk, "usage_metadata", "usageMetadata")
                    if usage_meta:
                        cache_read = (
                            _get_value(
                                usage_meta,
                                "cached_content_token_count",
                                "cachedContentTokenCount",
                            )
                            or 0
                        )
                        prompt_tokens = (
                            _get_value(
                                usage_meta, "prompt_token_count", "promptTokenCount"
                            )
                            or 0
                        )
                        output_tokens = (
                            _get_value(
                                usage_meta,
                                "candidates_token_count",
                                "candidatesTokenCount",
                            )
                            or 0
                        ) + (
                            _get_value(
                                usage_meta,
                                "thoughts_token_count",
                                "thoughtsTokenCount",
                            )
                            or 0
                        )
                        usage = Usage(
                            input_tokens=max(0, prompt_tokens - cache_read),
                            output_tokens=output_tokens,
                            cache_read=cache_read,
                            cache_write=0,
                        )

                if any(isinstance(block, ToolCall) for block in content_blocks):
                    stop_reason = StopReason.TOOL_USE

                message = AssistantMessage(
                    role="assistant",
                    content=content_blocks,
                    api="google-generative-ai",
                    provider=self.model_provider,
                    model=self.model_name,
                    usage=usage,
                    stop_reason=stop_reason,
                )
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)
                _log.info(
                    "Google stream end: stop_reason=%s usage_input=%s usage_output=%s",
                    stop_reason,
                    usage.input_tokens,
                    usage.output_tokens,
                )
            except Exception as error:
                error_detail = format_exception(error)
                log_exception(_log, "Google stream error", error, model=self.model_name)
                message = AssistantMessage(
                    role="assistant",
                    content=[TextContent(type="text", text="")],
                    api="google-generative-ai",
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

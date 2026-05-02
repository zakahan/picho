from __future__ import annotations

import asyncio
import json

from .base import Model
from ..stream import (
    EventStream,
    StreamEvent,
    AssistantMessageEvent,
    AssistantMessageEventType,
)
from ..types import (
    AssistantMessage,
    Context,
    StreamOptions,
    StopReason,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

default_mock_model = "mock-model"
default_mock_base_url = "mock://local"


class MockModel(Model):
    api = "mock"

    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[StreamEvent, AssistantMessage]:
        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data if e.type == "message_end" else None,
        )

        async def produce() -> None:
            tool_result_text = _get_last_tool_result_text(context)
            user_text = _get_last_user_text(context)
            tool_request = (
                None if tool_result_text else _parse_mock_tool_request(user_text)
            )
            response_text = tool_result_text or user_text or "Mock response"

            if (
                options
                and options.signal
                and getattr(options.signal, "is_set", lambda: False)()
            ):
                message = AssistantMessage(
                    content=[TextContent(type="text", text="")],
                    api=self.api,
                    provider=self.model_provider,
                    model=self.model_name,
                    stop_reason=StopReason.ABORTED,
                    error_message="Request was aborted",
                )
                stream.push(StreamEvent(type="message_start"))
                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)
                return

            stream.push(StreamEvent(type="message_start"))
            if tool_request:
                message = AssistantMessage(
                    content=[
                        ToolCall(
                            id="mock_tool_call_1",
                            name=tool_request["name"],
                            arguments=tool_request["arguments"],
                        )
                    ],
                    api=self.api,
                    provider=self.model_provider,
                    model=self.model_name,
                    stop_reason=StopReason.TOOL_USE,
                )

                stream.push(StreamEvent(type="message_end", data=message))
                stream.end(message)
                return

            stream.push(
                StreamEvent(
                    type="content_delta",
                    data=AssistantMessageEvent(
                        type=AssistantMessageEventType.TEXT_DELTA,
                        delta=response_text,
                    ),
                )
            )

            message = AssistantMessage(
                content=[TextContent(type="text", text=response_text)],
                api=self.api,
                provider=self.model_provider,
                model=self.model_name,
                stop_reason=StopReason.STOP,
            )

            stream.push(StreamEvent(type="message_end", data=message))
            stream.end(message)

        asyncio.create_task(produce())
        return stream


def _parse_mock_tool_request(user_text: str) -> dict | None:
    prefix = "mock_tool_call:"
    if not user_text.startswith(prefix):
        return None

    payload = json.loads(user_text[len(prefix) :])
    name = payload.get("name")
    arguments = payload.get("arguments", {})
    if not isinstance(name, str) or not name:
        raise ValueError("mock_tool_call payload must include a non-empty string name")
    if not isinstance(arguments, dict):
        raise ValueError("mock_tool_call payload arguments must be an object")
    return {
        "name": name,
        "arguments": arguments,
    }


def _get_last_tool_result_text(context: Context) -> str:
    for message in reversed(context.messages):
        if not isinstance(message, ToolResultMessage):
            continue

        text_parts: list[str] = []
        for block in message.content:
            if isinstance(block, TextContent) and block.text.strip():
                text_parts.append(block.text)
        if text_parts:
            return "\n".join(text_parts)
    return ""


def _get_last_user_text(context: Context) -> str:
    for message in reversed(context.messages):
        if isinstance(message, UserMessage):
            if isinstance(message.content, str):
                if message.content.strip():
                    return message.content
                continue

            text_parts: list[str] = []
            for block in message.content:
                if isinstance(block, TextContent) and block.text.strip():
                    text_parts.append(block.text)
            if text_parts:
                return "\n".join(text_parts)
    return ""

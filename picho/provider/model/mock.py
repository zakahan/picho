from __future__ import annotations

import asyncio

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
            user_text = _get_last_user_text(context)
            response_text = user_text or "Mock response"

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

"""
Event Stream - Used for streaming output of LLM responses

Provides asynchronous generator-style streaming output capability.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Generic, TypeVar
from enum import Enum

from ..logger import get_logger, log_exception

_log = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class AssistantMessageEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"


@dataclass
class AssistantMessageEvent:
    type: AssistantMessageEventType
    delta: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEvent:
    type: str
    data: Any = None


class EventStream(Generic[T, R]):
    def __init__(
        self,
        is_terminal: Callable[[T], bool],
        extract_result: Callable[[T], R],
    ):
        self._queue: asyncio.Queue[T | None] = asyncio.Queue()
        self._is_terminal = is_terminal
        self._extract_result = extract_result
        self._result: R | None = None
        self._ended = False
        self._error: Exception | None = None

    def push(self, event: T) -> None:
        self._queue.put_nowait(event)

    def end(self, result: R) -> None:
        self._result = result
        self._ended = True
        self._queue.put_nowait(None)

    def set_error(self, error: Exception) -> None:
        log_exception(_log, "EventStream error", error)
        self._error = error
        self._ended = True
        self._queue.put_nowait(None)

    async def __aiter__(self) -> AsyncGenerator[T, None]:
        while True:
            event = await self._queue.get()
            if event is None:
                if self._error:
                    raise self._error
                break
            yield event
            if self._is_terminal(event):
                if self._error:
                    raise self._error
                break

    @property
    def result(self) -> R | None:
        return self._result

    @property
    def error(self) -> Exception | None:
        return self._error

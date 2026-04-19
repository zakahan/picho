"""
pi-agent-core type definitions

Define the core types required for the Agent runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Union

from ..provider.model import Model
from ..provider.types import (
    Message,
    ToolResultMessage,
    ThinkingLevel,
    Context,
)
from ..tool import Tool
from ..tool import ToolResult


@dataclass
class RunContext:
    agent_name: str = ""
    invocation_id: str = ""
    session_id: str = ""
    session_file: str = ""
    workspace: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    context: Context | None = None


CallbackContext = RunContext


BeforeAgentCallback = Callable[
    [RunContext], Union[None, Message, Awaitable[None | Message]]
]
AfterAgentCallback = Callable[[RunContext, list[Message]], Union[None, Awaitable[None]]]
BeforeModelCallback = Callable[
    [RunContext, Context], Union[None, Message, Awaitable[None | Message]]
]
AfterModelCallback = Callable[
    [RunContext, Message], Union[None, Message, Awaitable[None | Message]]
]
BeforeToolCallback = Callable[
    [RunContext, str, dict[str, Any]],
    Union[None, ToolResult, Awaitable[None | ToolResult]],
]
AfterToolCallback = Callable[
    [RunContext, str, dict[str, Any], ToolResult],
    Union[None, ToolResult, Awaitable[None | ToolResult]],
]

CallbackType = Union[
    BeforeAgentCallback,
    AfterAgentCallback,
    BeforeModelCallback,
    AfterModelCallback,
    BeforeToolCallback,
    AfterToolCallback,
]

CALLBACK_KEYS = [
    "before_agent_callback",
    "after_agent_callback",
    "before_model_callback",
    "after_model_callback",
    "before_tool_callback",
    "after_tool_callback",
]


@dataclass
class LoopHooks:
    before_agent: list[BeforeAgentCallback] = field(default_factory=list)
    after_agent: list[AfterAgentCallback] = field(default_factory=list)
    before_model: list[BeforeModelCallback] = field(default_factory=list)
    after_model: list[AfterModelCallback] = field(default_factory=list)
    before_tool: list[BeforeToolCallback] = field(default_factory=list)
    after_tool: list[AfterToolCallback] = field(default_factory=list)

    @classmethod
    def from_callbacks(
        cls, callbacks: dict[str, list[CallbackType]] | None = None
    ) -> "LoopHooks":
        callback_map = callbacks or {k: [] for k in CALLBACK_KEYS}
        return cls(
            before_agent=list(callback_map.get("before_agent_callback", [])),
            after_agent=list(callback_map.get("after_agent_callback", [])),
            before_model=list(callback_map.get("before_model_callback", [])),
            after_model=list(callback_map.get("after_model_callback", [])),
            before_tool=list(callback_map.get("before_tool_callback", [])),
            after_tool=list(callback_map.get("after_tool_callback", [])),
        )


@dataclass
class AgentEvent:
    type: str
    message: Message | None = None
    tool_call_id: str = ""
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    is_error: bool = False
    assistant_event: Any = None
    messages: list[Message] = field(default_factory=list)
    tool_results: list[ToolResultMessage] = field(default_factory=list)


@dataclass
class AgentLoopConfig:
    model: Model | None = None
    thinking_level: ThinkingLevel = "auto"
    temperature: float | None = None
    max_tokens: int | None = None
    get_steering_messages: Callable[[], Awaitable[list[Message]]] | None = None
    get_follow_up_messages: Callable[[], Awaitable[list[Message]]] | None = None
    on_payload: Callable[[Any, Model], Any] | None = None
    signal: asyncio.Event | None = None
    callbacks: dict[str, list[CallbackType]] = field(
        default_factory=lambda: {k: [] for k in CALLBACK_KEYS}
    )
    callback_context: RunContext | None = None
    hooks: LoopHooks = field(default_factory=LoopHooks)
    run_context: RunContext | None = None

    def resolve_hooks(self) -> LoopHooks:
        if any(
            (
                self.hooks.before_agent,
                self.hooks.after_agent,
                self.hooks.before_model,
                self.hooks.after_model,
                self.hooks.before_tool,
                self.hooks.after_tool,
            )
        ):
            return self.hooks
        return LoopHooks.from_callbacks(self.callbacks)

    def resolve_run_context(self) -> RunContext | None:
        return self.run_context or self.callback_context


@dataclass
class AgentState:
    instructions: str = ""
    model: Model | None = None
    thinking_level: ThinkingLevel = "auto"
    tools: list[Tool] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    is_streaming: bool = False
    stream_message: Message | None = None
    pending_tool_calls: set[str] = field(default_factory=set)
    error: str | None = None

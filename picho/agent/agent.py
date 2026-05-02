"""
Agent

High-level agent class that wraps the agent loop with state management.
This module references pi-mono's agent implementation approach.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable, Literal, TYPE_CHECKING

from .loop import agent_loop, agent_loop_continue, AgentEventStream
from .types import (
    AgentEvent,
    AgentLoopConfig,
    AgentState,
    CallbackType,
    CALLBACK_KEYS,
    LoopHooks,
    RunContext,
    ThinkingLevel,
)
from ..provider.model import Model
from ..provider.types import (
    Message,
    TextContent,
    AssistantMessage,
    StopReason,
    UserMessage,
    Context,
)
from ..tool import Tool
from ..logger import (
    format_exception,
    get_log_context,
    get_logger,
    log_context,
    log_exception,
)
from ..observability import (
    get_tracer,
    record_exception,
    set_ok_status,
    set_span_attributes,
)

if TYPE_CHECKING:
    from ..skills import Skill

_log = get_logger(__name__)
_tracer = get_tracer(__name__)


class Agent:
    def __init__(
        self,
        model: Model | None = None,
        instructions: str = "",
        thinking_level: ThinkingLevel = "auto",
        tools: list[Tool] | None = None,
        messages: list[Message] | None = None,
        steering_mode: Literal["all", "one-at-a-time"] = "one-at-a-time",
        follow_up_mode: Literal["all", "one-at-a-time"] = "one-at-a-time",
        callbacks: dict[str, CallbackType | list[CallbackType]] | None = None,
        skills: list["Skill"] | None = None,
        skill_paths: list[str] | None = None,
    ):
        self._base_instructions = instructions
        self._skills: list["Skill"] = skills or []
        self._skill_paths: list[str] = skill_paths or []

        self._state = AgentState(
            instructions=self._build_instructions(instructions),
            model=model,
            thinking_level=thinking_level,
            tools=tools or [],
            messages=messages or [],
        )

        # _log.error(f"instructions={self._state.instructions}")

        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._abort_event: asyncio.Event | None = None
        self._steering_queue: list[Message] = []
        self._follow_up_queue: list[Message] = []
        self._steering_mode = steering_mode
        self._follow_up_mode = follow_up_mode
        self._running_prompt: asyncio.Task | None = None
        self._callbacks: dict[str, list[CallbackType]] = {k: [] for k in CALLBACK_KEYS}

        if callbacks:
            for key, value in callbacks.items():
                if key in self._callbacks:
                    if isinstance(value, list):
                        self._callbacks[key].extend(value)
                    else:
                        self._callbacks[key].append(value)

        self._log_init_info()

    def _log_init_info(self):
        model = self._state.model
        if model:
            model_info = f"provider={model.model_provider} model={model.model_name}"
            if hasattr(model, "base_url") and model.base_url:
                model_info += f" base_url={model.base_url}"
            if hasattr(model, "input_types"):
                input_types = model.input_types or []
                model_info += f" input_types={input_types}"
        else:
            model_info = "None"

        tools = self._state.tools or []
        tool_names = [t.name for t in tools] if tools else []

        skills = self._skills or []
        skill_names = [s.name for s in skills] if skills else []

        _log.info(f"Agent initialized | {model_info}")
        _log.info(
            f"Agent config | thinking={self._state.thinking_level} tools={tool_names} skills={skill_names}"
        )

    def _build_instructions(self, base_instructions: str) -> str:
        """Build instructions with skills prompt injected."""
        result = base_instructions or ""

        if self._skills:
            from ..skills import format_skills_for_prompt

            skills_prompt = format_skills_for_prompt(self._skills)
            if skills_prompt:
                result += skills_prompt

        skill_names = [s.name for s in self._skills] if self._skills else []
        if "skill-creator" in skill_names and self._skill_paths:
            skill_path_hint = (
                "\n\n<skill_path_instruction>\n"
                f"When creating new skills, save them to: {self._skill_paths[0]}\n"
                "</skill_path_instruction>"
            )
            result += skill_path_hint

        return result

    def set_skills(self, skills: list["Skill"]) -> None:
        """Set skills and rebuild instructions."""
        self._skills = skills
        self._state.instructions = self._build_instructions(self._base_instructions)

    def get_skills(self) -> list["Skill"]:
        """Get current skills."""
        return self._skills

    @property
    def state(self) -> AgentState:
        return self._state

    def subscribe(self, fn: Callable[[AgentEvent], None]) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn) if fn in self._listeners else None

    def set_instructions(self, v: str):
        self._base_instructions = v
        self._state.instructions = self._build_instructions(v)

    def set_model(self, m: Model):
        self._state.model = m

    def set_thinking_level(self, level: ThinkingLevel):
        self._state.thinking_level = level

    def set_steering_mode(self, mode: Literal["all", "one-at-a-time"]):
        self._steering_mode = mode

    def get_steering_mode(self) -> Literal["all", "one-at-a-time"]:
        return self._steering_mode

    def set_follow_up_mode(self, mode: Literal["all", "one-at-a-time"]):
        self._follow_up_mode = mode

    def get_follow_up_mode(self) -> Literal["all", "one-at-a-time"]:
        return self._follow_up_mode

    def set_tools(self, tools: list[Tool]):
        self._state.tools = tools

    def register_callback(
        self, callback_type: str, fn: CallbackType
    ) -> Callable[[], None]:
        if callback_type not in self._callbacks:
            raise ValueError(f"Unknown callback type: {callback_type}")
        self._callbacks[callback_type].append(fn)
        return (
            lambda: self._callbacks[callback_type].remove(fn)
            if fn in self._callbacks[callback_type]
            else None
        )

    def unregister_callback(self, callback_type: str, fn: CallbackType):
        if callback_type in self._callbacks and fn in self._callbacks[callback_type]:
            self._callbacks[callback_type].remove(fn)

    def clear_callbacks(self, callback_type: str | None = None):
        if callback_type:
            if callback_type in self._callbacks:
                self._callbacks[callback_type].clear()
        else:
            for key in self._callbacks:
                self._callbacks[key].clear()

    def get_callbacks(self, callback_type: str) -> list[CallbackType]:
        return self._callbacks.get(callback_type, [])

    def replace_messages(self, messages: list[Message]):
        self._state.messages = list(messages)

    def append_message(self, message: Message):
        self._state.messages.append(message)

    def steer(self, message: Message):
        self._steering_queue.append(message)

    def follow_up(self, message: Message):
        self._follow_up_queue.append(message)

    def clear_steering_queue(self):
        self._steering_queue.clear()

    def clear_follow_up_queue(self):
        self._follow_up_queue.clear()

    def clear_all_queues(self):
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    def has_queued_messages(self) -> bool:
        return len(self._steering_queue) > 0 or len(self._follow_up_queue) > 0

    def _dequeue_steering_messages(self) -> list[Message]:
        if self._steering_mode == "one-at-a-time":
            if self._steering_queue:
                return [self._steering_queue.pop(0)]
            return []

        messages = list(self._steering_queue)
        self._steering_queue.clear()
        return messages

    def _dequeue_follow_up_messages(self) -> list[Message]:
        if self._follow_up_mode == "one-at-a-time":
            if self._follow_up_queue:
                return [self._follow_up_queue.pop(0)]
            return []

        messages = list(self._follow_up_queue)
        self._follow_up_queue.clear()
        return messages

    def clear_messages(self):
        self._state.messages.clear()

    def abort(self):
        if self._abort_event:
            self._abort_event.set()
            self._steering_queue.clear()
            self._follow_up_queue.clear()
            _log.info("Abort signal set, queues cleared")

    async def wait_for_idle(self) -> None:
        if self._running_prompt:
            try:
                await self._running_prompt
            except asyncio.CancelledError:
                pass

    def reset(self):
        self._state.messages.clear()
        self._state.is_streaming = False
        self._state.pending_tool_calls.clear()
        self._state.error = None
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    async def prompt(
        self,
        message: str | Message | list[Message],
        run_context: RunContext | None = None,
    ) -> None:
        if self._state.is_streaming:
            raise RuntimeError(
                "Agent is already processing a prompt. Use steer() or followUp() to queue messages."
            )

        model = self._state.model
        if not model:
            raise RuntimeError("No model configured")

        messages: list[Message]

        if isinstance(message, list):
            messages = message
        elif isinstance(message, str):
            messages = [UserMessage(content=[TextContent(type="text", text=message)])]
        else:
            messages = [message]

        run_context = self._ensure_run_context(run_context)
        with log_context(invocation_id=run_context.invocation_id):
            _log.debug(f"Prompt start messages={len(messages)}")
            await self._invoke(initial_messages=messages, run_context=run_context)
            _log.info("Prompt end")

    async def continue_(self, run_context: RunContext | None = None):
        if self._state.is_streaming:
            raise RuntimeError(
                "Agent is already processing. Wait for completion before continuing."
            )

        messages = self._state.messages
        if not messages:
            raise RuntimeError("No messages to continue from")

        if messages[-1].role == "assistant":
            queued_steering = self._dequeue_steering_messages()
            if queued_steering:
                run_context = self._ensure_run_context(run_context)
                await self._invoke(
                    initial_messages=queued_steering,
                    skip_initial_steering_poll=True,
                    run_context=run_context,
                )
                return

            queued_follow_up = self._dequeue_follow_up_messages()
            if queued_follow_up:
                run_context = self._ensure_run_context(run_context)
                await self._invoke(
                    initial_messages=queued_follow_up,
                    run_context=run_context,
                )
                return

            raise RuntimeError("Cannot continue from message role: assistant")

        run_context = self._ensure_run_context(run_context)
        with log_context(invocation_id=run_context.invocation_id):
            _log.info("Continue start")
            await self._invoke(run_context=run_context)
            _log.info("Continue end")

    def _build_context(self) -> Context:
        return Context(
            instructions=self._state.instructions,
            messages=list(self._state.messages),
            tools=self._state.tools,
        )

    def _ensure_run_context(self, run_context: RunContext | None = None) -> RunContext:
        base = run_context or RunContext()
        if base.invocation_id:
            return base
        return RunContext(
            agent_name=base.agent_name,
            invocation_id=str(uuid.uuid4()),
            session_id=base.session_id,
            session_file=base.session_file,
            workspace=base.workspace,
            state=dict(base.state),
            context=base.context,
        )

    def _build_run_context(
        self,
        context: Context,
        run_context: RunContext | None = None,
    ) -> RunContext:
        base = run_context or RunContext()
        log_ctx = get_log_context()
        return RunContext(
            agent_name=base.agent_name or "agent",
            invocation_id=base.invocation_id or str(uuid.uuid4()),
            session_id=base.session_id or log_ctx.get("session_id", ""),
            session_file=base.session_file or log_ctx.get("session_file", ""),
            workspace=base.workspace or log_ctx.get("workspace", ""),
            state=dict(base.state),
            context=context,
        )

    def _build_loop_hooks(self) -> LoopHooks:
        return LoopHooks.from_callbacks(self._callbacks)

    async def _consume_stream(
        self,
        stream: AgentEventStream,
        *,
        model: Model,
        invocation_id: str,
        start_time: float,
    ) -> None:
        partial: Message | None = None
        try:
            async for event in stream:
                if event.type == "message_start":
                    partial = event.message
                    self._state.stream_message = event.message
                elif event.type == "message_update":
                    partial = event.message
                    self._state.stream_message = event.message
                elif event.type == "message_end":
                    partial = None
                    self._state.stream_message = None
                    self.append_message(event.message)
                elif event.type == "tool_execution_start":
                    self._state.pending_tool_calls.add(event.tool_call_id)
                elif event.type == "tool_execution_end":
                    self._state.pending_tool_calls.discard(event.tool_call_id)
                elif event.type == "turn_end":
                    if event.message.role == "assistant":
                        error_msg = getattr(event.message, "error_message", None)
                        if error_msg:
                            self._state.error = error_msg
                elif event.type == "agent_end":
                    self._state.is_streaming = False
                    self._state.stream_message = None

                self._emit(event)

            if partial and partial.role == "assistant":
                content = getattr(partial, "content", [])
                has_content = any(
                    (isinstance(c, TextContent) and c.text.strip())
                    or (hasattr(c, "thinking") and c.thinking.strip())
                    or (hasattr(c, "name") and c.name.strip())
                    for c in content
                )
                if has_content:
                    self.append_message(partial)
                elif self._abort_event and self._abort_event.is_set():
                    raise RuntimeError("Request was aborted")

        except Exception as err:
            error_message = format_exception(err)
            log_exception(_log, "Agent run failed", err, invocation_id=invocation_id)

            error_msg = AssistantMessage(
                role="assistant",
                content=[TextContent(type="text", text="")],
                api=model.api if hasattr(model, "api") else "",
                provider=model.model_provider,
                model=model.model_name,
                usage=type(
                    "Usage",
                    (),
                    {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read": 0,
                        "cache_write": 0,
                        "total_tokens": 0,
                    },
                )(),
                stop_reason=StopReason.ABORTED
                if self._abort_event and self._abort_event.is_set()
                else StopReason.ERROR,
                error_message=error_message,
            )

            self.append_message(error_msg)
            self._state.error = error_message
            self._emit(AgentEvent(type="message_start", message=error_msg))
            self._emit(AgentEvent(type="message_end", message=error_msg))
            self._emit(AgentEvent(type="agent_end", messages=[error_msg]))
        finally:
            self._state.is_streaming = False
            self._state.stream_message = None
            self._state.pending_tool_calls.clear()
            self._abort_event = None
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            status = "ERROR" if self._state.error else "OK"
            _log.info(f"Agent complete | {status} | {elapsed_ms}ms")

    async def _invoke(
        self,
        initial_messages: list[Message] | None = None,
        *,
        skip_initial_steering_poll: bool = False,
        run_context: RunContext | None = None,
    ) -> None:
        model = self._state.model
        if not model:
            raise RuntimeError("No model configured")

        start_time = time.monotonic()
        self._abort_event = asyncio.Event()
        self._state.is_streaming = True
        self._state.error = None

        context = self._build_context()

        skip_steering = skip_initial_steering_poll

        async def get_steering():
            nonlocal skip_steering
            if skip_steering:
                skip_steering = False
                return []
            return self._dequeue_steering_messages()

        async def get_follow_up():
            return self._dequeue_follow_up_messages()

        resolved_run_context = self._build_run_context(context, run_context)
        invocation_id = resolved_run_context.invocation_id

        config = AgentLoopConfig(
            model=model,
            thinking_level=self._state.thinking_level,
            get_steering_messages=get_steering,
            get_follow_up_messages=get_follow_up,
            on_payload=resolved_run_context.state.get("on_payload"),
            callbacks=self._callbacks,
            callback_context=resolved_run_context,
            hooks=self._build_loop_hooks(),
            run_context=resolved_run_context,
        )

        with log_context(invocation_id=invocation_id):
            with _tracer.start_as_current_span("picho.agent.run") as span:
                set_span_attributes(
                    span,
                    {
                        "gen_ai.operation.name": "chat",
                        "gen_ai.conversation.id": resolved_run_context.session_id,
                        "picho.invocation.id": invocation_id,
                        "picho.agent.name": resolved_run_context.agent_name,
                        "picho.workspace": resolved_run_context.workspace,
                        "gen_ai.provider.name": getattr(model, "model_provider", ""),
                        "gen_ai.request.model": getattr(model, "model_name", ""),
                        "picho.context.message_count": len(context.messages),
                        "picho.steering_queue.size": len(self._steering_queue),
                        "picho.follow_up_queue.size": len(self._follow_up_queue),
                    },
                )
                _log.debug(
                    "Agent run start "
                    f"model={getattr(model, 'model_name', 'unknown')} "
                    f"messages={len(context.messages)} "
                    f"steering_queue={len(self._steering_queue)} "
                    f"follow_up_queue={len(self._follow_up_queue)}"
                )
                try:
                    if initial_messages:
                        stream = await agent_loop(
                            initial_messages, context, config, self._abort_event
                        )
                    else:
                        stream = await agent_loop_continue(
                            context, config, self._abort_event
                        )
                    await self._consume_stream(
                        stream,
                        model=model,
                        invocation_id=invocation_id,
                        start_time=start_time,
                    )
                except Exception as err:
                    record_exception(span, err)
                    raise
                finally:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    status = "error" if self._state.error else "ok"
                    if self._abort_event and self._abort_event.is_set():
                        status = "aborted"
                    set_span_attributes(
                        span,
                        {
                            "picho.status": status,
                            "picho.duration.ms": elapsed_ms,
                        },
                    )
                    if status == "ok":
                        set_ok_status(span)

    def _emit(self, event: AgentEvent):
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as err:
                log_exception(
                    _log,
                    "Agent listener failed",
                    err,
                    event_type=event.type,
                )

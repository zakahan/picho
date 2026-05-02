"""
Agent Loop

Core agent loop implementation that handles LLM interaction and tool execution.
This module's core loop design references pi-mono's working implementation.
"""

import asyncio
import uuid
import time
from typing import Any, Callable, Awaitable

from .types import (
    AgentEvent,
    AgentLoopConfig,
    LoopHooks,
    RunContext,
)
from ..provider.stream import EventStream
from ..provider.types import (
    Context,
    ImageBase64Content,
    ImageFileIdContent,
    ImageUrlContent,
    ToolCall,
    ToolResultMessage,
    TextContent,
    AssistantMessage,
    StopReason,
    Message,
    Tool,
    ThinkingContent,
    Usage,
    VideoFileIdContent,
    normalize_content_blocks,
)
from ..tool import ToolResult
from ..logger import format_exception, get_logger, log_exception
from ..observability import (
    add_event,
    get_tracer,
    record_exception,
    set_message_attributes,
    set_ok_status,
    set_span_attributes,
    set_usage_attributes,
)
from ..observability.serialize import preview_json

_log = get_logger(__name__)
_tracer = get_tracer(__name__)


def _format_tool_args(tool_name: str, args: dict) -> str:
    key_fields = {
        "read": "path",
        "write": "path",
        "edit": ["path", "old_str"],
        "grep": ["pattern", "path"],
        "bash": "command",
        "glob": "pattern",
    }

    keys = key_fields.get(tool_name, [])
    if isinstance(keys, str):
        keys = [keys]

    if not keys:
        keys = list(args.keys())[:2]

    parts = []
    for key in keys:
        if key in args:
            val = args[key]
            if isinstance(val, str):
                if len(val) > 50:
                    val = val[:50] + "..."
            parts.append(f"{key}={val!r}")

    return " | ".join(parts) if parts else "no args"


def _estimate_output_block_count(message: AssistantMessage) -> int:
    return len(message.content or [])


def _is_rendered_output_block(block: Any) -> bool:
    return isinstance(
        block,
        (
            TextContent,
            ThinkingContent,
            ImageBase64Content,
            ImageUrlContent,
            ImageFileIdContent,
            VideoFileIdContent,
        ),
    )


def _derive_tpot_ms(
    usage: Usage,
    duration_ms: int,
    ttft_ms: int | None,
) -> float | None:
    if ttft_ms is None or usage.output_tokens <= 0:
        return None
    remaining_ms = max(duration_ms - ttft_ms, 0)
    return round(remaining_ms / usage.output_tokens, 3)


async def _run_callbacks(
    callbacks: list[Callable],
    *args,
    **kwargs,
) -> Any:
    for fn in callbacks:
        try:
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        except Exception as err:
            log_exception(
                _log,
                "Callback execution failed",
                err,
                callback=getattr(fn, "__name__", fn.__class__.__name__),
            )
    return None


class AgentEventStream(EventStream[AgentEvent, list[Message]]):
    def __init__(self):
        super().__init__(
            is_terminal=lambda e: e.type == "agent_end",
            extract_result=lambda e: e.messages if e.type == "agent_end" else [],
        )


def _create_agent_stream() -> AgentEventStream:
    return AgentEventStream()


def _validate_tool_arguments(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError(
            f"Tool {tool.name} arguments must be an object, got {type(arguments).__name__}"
        )

    parameters = tool.parameters
    if not parameters:
        return arguments

    if parameters.type and parameters.type != "object":
        raise ValueError(
            f"Tool {tool.name} parameters must use object schema, got {parameters.type}"
        )

    missing = [name for name in parameters.required or [] if name not in arguments]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Tool {tool.name} missing required arguments: {missing_list}")

    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    for name, value in arguments.items():
        schema = (parameters.properties or {}).get(name)
        if not schema:
            continue

        expected_type = schema.get("type")
        if not expected_type:
            continue

        python_type = type_map.get(expected_type)
        if not python_type:
            continue

        if expected_type == "integer":
            is_valid = isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == "number":
            is_valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            is_valid = isinstance(value, python_type)

        if not is_valid:
            raise ValueError(
                f"Tool {tool.name} argument {name!r} must be {expected_type}, "
                f"got {type(value).__name__}"
            )

    return arguments


async def agent_loop(
    prompts: list[Message],
    context: Context,
    config: AgentLoopConfig,
    signal: asyncio.Event | None = None,
) -> AgentEventStream:
    stream = _create_agent_stream()

    async def run():
        _log.debug(
            f"Agent loop start prompts={len(prompts)} context_messages={len(context.messages)}"
        )
        new_messages: list[Message] = list(prompts)
        current_context = Context(
            instructions=context.instructions,
            messages=[*context.messages, *prompts],
            tools=context.tools,
        )

        hooks = config.resolve_hooks()
        cb_ctx = config.resolve_run_context() or RunContext(
            agent_name="agent",
            invocation_id=str(uuid.uuid4()),
            state={},
            context=current_context,
        )
        cb_ctx.context = current_context

        override_message = await _run_callbacks(hooks.before_agent, cb_ctx)

        if override_message:
            stream.push(AgentEvent(type="agent_start"))
            stream.push(AgentEvent(type="message_start", message=override_message))
            stream.push(AgentEvent(type="message_end", message=override_message))
            stream.push(AgentEvent(type="agent_end", messages=[override_message]))
            stream.end([override_message])

            await _run_callbacks(hooks.after_agent, cb_ctx, [override_message])
            return

        stream.push(AgentEvent(type="agent_start"))
        stream.push(AgentEvent(type="turn_start"))

        for prompt in prompts:
            stream.push(AgentEvent(type="message_start", message=prompt))
            stream.push(AgentEvent(type="message_end", message=prompt))

        await _run_loop(
            current_context, new_messages, config, signal, stream, cb_ctx, hooks
        )

        await _run_callbacks(hooks.after_agent, cb_ctx, new_messages)

    asyncio.create_task(run())
    return stream


async def agent_loop_continue(
    context: Context,
    config: AgentLoopConfig,
    signal: asyncio.Event | None = None,
) -> AgentEventStream:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")

    last_message = context.messages[-1]
    if last_message.role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    stream = _create_agent_stream()

    async def run():
        new_messages: list[Message] = []
        current_context = Context(
            instructions=context.instructions,
            messages=list(context.messages),
            tools=context.tools,
        )

        hooks = config.resolve_hooks()
        cb_ctx = config.resolve_run_context() or RunContext(
            agent_name="agent",
            invocation_id=str(uuid.uuid4()),
            state={},
            context=current_context,
        )
        cb_ctx.context = current_context

        override_message = await _run_callbacks(hooks.before_agent, cb_ctx)

        if override_message:
            stream.push(AgentEvent(type="agent_start"))
            stream.push(AgentEvent(type="message_start", message=override_message))
            stream.push(AgentEvent(type="message_end", message=override_message))
            stream.push(AgentEvent(type="agent_end", messages=[override_message]))
            stream.end([override_message])

            await _run_callbacks(hooks.after_agent, cb_ctx, [override_message])
            return

        stream.push(AgentEvent(type="agent_start"))
        stream.push(AgentEvent(type="turn_start"))

        await _run_loop(
            current_context, new_messages, config, signal, stream, cb_ctx, hooks
        )

        await _run_callbacks(hooks.after_agent, cb_ctx, new_messages)

    asyncio.create_task(run())
    return stream


async def _run_loop(
    current_context: Context,
    new_messages: list[Message],
    config: AgentLoopConfig,
    signal: asyncio.Event | None,
    stream: AgentEventStream,
    cb_ctx: RunContext,
    hooks: LoopHooks,
) -> None:
    first_turn = True
    turn_index = 0
    pending_messages: list[Message] = []

    if config.get_steering_messages:
        pending_messages = await config.get_steering_messages() or []

    while True:
        has_more_tool_calls = True
        steering_after_tools: list[Message] | None = None

        while has_more_tool_calls or pending_messages:
            turn_index += 1
            with _tracer.start_as_current_span("picho.agent.turn") as turn_span:
                set_span_attributes(
                    turn_span,
                    {
                        "gen_ai.conversation.id": cb_ctx.session_id,
                        "picho.invocation.id": cb_ctx.invocation_id,
                        "picho.agent.name": cb_ctx.agent_name,
                        "picho.workspace": cb_ctx.workspace,
                        "picho.turn.index": turn_index,
                        "picho.context.message_count.before": len(
                            current_context.messages
                        ),
                        "picho.pending_messages.before": len(pending_messages),
                    },
                )

                if not first_turn:
                    stream.push(AgentEvent(type="turn_start"))
                else:
                    first_turn = False

                if pending_messages:
                    for message in pending_messages:
                        stream.push(AgentEvent(type="message_start", message=message))
                        stream.push(AgentEvent(type="message_end", message=message))
                        current_context.messages.append(message)
                        new_messages.append(message)
                    pending_messages = []

                cb_ctx.context = current_context
                override_message = await _run_callbacks(
                    hooks.before_model, cb_ctx, current_context
                )

                if override_message:
                    modified_message = await _run_callbacks(
                        hooks.after_model, cb_ctx, override_message
                    )
                    if modified_message:
                        override_message = modified_message

                    current_context.messages.append(override_message)
                    new_messages.append(override_message)
                    stream.push(
                        AgentEvent(type="message_start", message=override_message)
                    )
                    stream.push(
                        AgentEvent(type="message_end", message=override_message)
                    )
                    set_message_attributes(
                        turn_span, "picho.output.message", override_message
                    )
                    set_span_attributes(
                        turn_span,
                        {
                            "picho.stop_reason": getattr(
                                override_message,
                                "stop_reason",
                                "override",
                            ),
                            "picho.tool_result_count": 0,
                            "picho.context.message_count.after": len(
                                current_context.messages
                            ),
                        },
                    )
                    set_ok_status(turn_span)

                    stream.push(
                        AgentEvent(
                            type="turn_end",
                            message=override_message,
                            tool_results=[],
                        )
                    )
                    stream.push(AgentEvent(type="agent_end", messages=new_messages))
                    stream.end(new_messages)
                    return

                stream_start = time.monotonic()
                message = await _stream_assistant_response(
                    current_context, config, signal, stream
                )
                stream_elapsed_ms = int((time.monotonic() - stream_start) * 1000)

                modified_message = await _run_callbacks(
                    hooks.after_model, cb_ctx, message
                )
                if modified_message:
                    message = modified_message

                current_context.messages.append(message)
                new_messages.append(message)
                stream.push(AgentEvent(type="message_start", message=message))
                stream.push(AgentEvent(type="message_end", message=message))

                if message.stop_reason in (StopReason.ERROR, StopReason.ABORTED):
                    set_message_attributes(turn_span, "picho.output.message", message)
                    set_span_attributes(
                        turn_span,
                        {
                            "picho.stop_reason": message.stop_reason.value,
                            "picho.stream.duration.ms": stream_elapsed_ms,
                            "picho.tool_result_count": 0,
                            "picho.context.message_count.after": len(
                                current_context.messages
                            ),
                        },
                    )
                    stream.push(
                        AgentEvent(
                            type="turn_end",
                            message=message,
                            tool_results=[],
                        )
                    )
                    stream.push(AgentEvent(type="agent_end", messages=new_messages))
                    stream.end(new_messages)
                    return

                tool_calls = [c for c in message.content if isinstance(c, ToolCall)]
                has_more_tool_calls = len(tool_calls) > 0
                _log.debug(
                    f"Model response stop_reason={message.stop_reason} tool_calls={len(tool_calls)} stream_ms={stream_elapsed_ms}"
                )

                tool_results: list[ToolResultMessage] = []
                if has_more_tool_calls:
                    execution_result = await _execute_tool_calls(
                        current_context.tools,
                        message,
                        signal,
                        stream,
                        config.get_steering_messages,
                        hooks,
                        cb_ctx,
                    )
                    tool_results = execution_result["tool_results"]
                    steering_after_tools = execution_result.get("steering_messages")

                    for result in tool_results:
                        current_context.messages.append(result)
                        new_messages.append(result)

                    if execution_result.get("aborted"):
                        set_message_attributes(
                            turn_span, "picho.output.message", message
                        )
                        set_span_attributes(
                            turn_span,
                            {
                                "picho.stop_reason": StopReason.ABORTED.value,
                                "picho.stream.duration.ms": stream_elapsed_ms,
                                "picho.tool_call_count": len(tool_calls),
                                "picho.tool_result_count": len(tool_results),
                                "picho.context.message_count.after": len(
                                    current_context.messages
                                ),
                            },
                        )
                        stream.push(
                            AgentEvent(
                                type="turn_end",
                                message=message,
                                tool_results=tool_results,
                            )
                        )
                        stream.push(AgentEvent(type="agent_end", messages=new_messages))
                        stream.end(new_messages)
                        return

                set_message_attributes(turn_span, "picho.output.message", message)
                set_span_attributes(
                    turn_span,
                    {
                        "picho.stop_reason": message.stop_reason.value,
                        "picho.stream.duration.ms": stream_elapsed_ms,
                        "picho.tool_call_count": len(tool_calls),
                        "picho.tool_result_count": len(tool_results),
                        "picho.context.message_count.after": len(
                            current_context.messages
                        ),
                    },
                )
                set_ok_status(turn_span)
                stream.push(
                    AgentEvent(
                        type="turn_end",
                        message=message,
                        tool_results=tool_results,
                    )
                )

                if steering_after_tools:
                    pending_messages = steering_after_tools
                    steering_after_tools = None
                elif config.get_steering_messages:
                    pending_messages = await config.get_steering_messages() or []

        if config.get_follow_up_messages:
            follow_up_messages = await config.get_follow_up_messages() or []
            if follow_up_messages:
                pending_messages = follow_up_messages
                continue

        break

    stream.push(AgentEvent(type="agent_end", messages=new_messages))
    stream.end(new_messages)


async def _stream_assistant_response(
    context: Context,
    config: AgentLoopConfig,
    signal: asyncio.Event | None,
    stream: AgentEventStream,
) -> AssistantMessage:
    from ..provider.types import StreamOptions

    options = StreamOptions(
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        thinking_level=config.thinking_level,
        signal=signal,
    )

    _log.debug(
        f"Model stream start messages={len(context.messages)} tools={len(context.tools or [])}"
    )
    run_context = config.resolve_run_context()
    llm_start = time.monotonic()
    first_token_ms: int | None = None
    response = None

    with _tracer.start_as_current_span("picho.llm.stream") as span:
        set_span_attributes(
            span,
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.conversation.id": run_context.session_id if run_context else "",
                "picho.invocation.id": run_context.invocation_id if run_context else "",
                "picho.agent.name": run_context.agent_name if run_context else "",
                "picho.workspace": run_context.workspace if run_context else "",
                "gen_ai.provider.name": getattr(config.model, "model_provider", ""),
                "gen_ai.request.model": getattr(config.model, "model_name", ""),
                "picho.context.message_count": len(context.messages),
                "picho.context.tool_count": len(context.tools or []),
                "gen_ai.request.max_tokens": config.max_tokens,
                "gen_ai.request.temperature": config.temperature,
                "picho.thinking_level": config.thinking_level,
                "picho.input.preview": preview_json(context.messages[-8:]),
            },
        )
        try:
            response = await config.model.stream(
                context,
                options,
            )

            async for event in response:
                if event.type == "message_start":
                    pass
                elif event.type == "content_delta":
                    if event.data and hasattr(event.data, "delta"):
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - llm_start) * 1000)
                            add_event(
                                span,
                                "picho.llm.first_token",
                                {
                                    "picho.ttft.ms": first_token_ms,
                                    "picho.delta.type": "content",
                                },
                            )
                        stream.push(
                            AgentEvent(
                                type="content_delta",
                                message=None,
                                assistant_event=event,
                            )
                        )
                elif event.type == "thinking_delta":
                    if event.data and hasattr(event.data, "delta"):
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - llm_start) * 1000)
                            add_event(
                                span,
                                "picho.llm.first_token",
                                {
                                    "picho.ttft.ms": first_token_ms,
                                    "picho.delta.type": "thinking",
                                },
                            )
                        stream.push(
                            AgentEvent(
                                type="thinking_delta",
                                message=None,
                                assistant_event=event,
                            )
                        )
                elif event.type == "tool_call_start":
                    if event.data:
                        _log.debug(
                            f"Tool call start id={event.data.tool_call_id} name={event.data.tool_name}"
                        )
                        add_event(
                            span,
                            "picho.llm.tool_call_start",
                            {
                                "gen_ai.tool.call.id": event.data.tool_call_id,
                                "gen_ai.tool.name": event.data.tool_name,
                            },
                        )
                        stream.push(
                            AgentEvent(
                                type="tool_call_start",
                                tool_call_id=event.data.tool_call_id,
                                tool_name=event.data.tool_name,
                                args={},
                            )
                        )
                elif event.type == "tool_call_delta":
                    if event.data:
                        stream.push(
                            AgentEvent(
                                type="tool_call_delta",
                                tool_call_id=event.data.tool_call_id,
                                args={},
                            )
                        )
                elif event.type == "message_end":
                    final_message = event.data
                    if final_message:
                        duration_ms = int((time.monotonic() - llm_start) * 1000)
                        tpot_ms = _derive_tpot_ms(
                            final_message.usage,
                            duration_ms,
                            first_token_ms,
                        )
                        set_usage_attributes(span, final_message.usage)
                        set_message_attributes(
                            span, "picho.output.message", final_message
                        )
                        set_span_attributes(
                            span,
                            {
                                "gen_ai.response.finish_reasons": [
                                    final_message.stop_reason.value
                                ],
                                "picho.duration.ms": duration_ms,
                                "picho.ttft.ms": first_token_ms,
                                "picho.tpot.ms": tpot_ms,
                                "picho.output.block_count": _estimate_output_block_count(
                                    final_message
                                ),
                                "picho.output.rendered_block_count": sum(
                                    1
                                    for block in final_message.content
                                    if _is_rendered_output_block(block)
                                ),
                            },
                        )
                        if final_message.stop_reason not in (
                            StopReason.ERROR,
                            StopReason.ABORTED,
                        ):
                            set_ok_status(span)
                        _log.debug("Model stream end")
                        return final_message
        except Exception as err:
            record_exception(span, err)
            raise

    if response is None:
        raise RuntimeError("Model stream did not initialize")
    return response.result


async def _execute_tool_calls(
    tools: list[Tool] | None,
    assistant_message: AssistantMessage,
    signal: asyncio.Event | None,
    stream: AgentEventStream,
    get_steering_messages: Callable[[], Awaitable[list[Message]]] | None,
    hooks: LoopHooks,
    cb_ctx: RunContext,
) -> dict[str, Any]:
    tool_calls = [c for c in assistant_message.content if isinstance(c, ToolCall)]
    results: list[ToolResultMessage] = []
    steering_messages: list[Message] | None = None

    for i, tool_call in enumerate(tool_calls):
        with _tracer.start_as_current_span("picho.tool.execute") as span:
            tool = None
            if tools:
                tool = next((t for t in tools if t.name == tool_call.name), None)

            set_span_attributes(
                span,
                {
                    "picho.invocation.id": cb_ctx.invocation_id,
                    "gen_ai.conversation.id": cb_ctx.session_id,
                    "picho.agent.name": cb_ctx.agent_name,
                    "picho.workspace": cb_ctx.workspace,
                    "gen_ai.tool.call.id": tool_call.id,
                    "gen_ai.tool.name": tool_call.name,
                    "picho.tool.args": preview_json(tool_call.arguments),
                },
            )

            override_result = await _run_callbacks(
                hooks.before_tool, cb_ctx, tool_call.name, tool_call.arguments
            )

            args_preview = _format_tool_args(tool_call.name, tool_call.arguments)
            _log.info(f"Tool: {tool_call.name} | {args_preview}")
            stream.push(
                AgentEvent(
                    type="tool_execution_start",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    args=tool_call.arguments,
                )
            )

            result: ToolResult
            is_error = False

            tool_start = time.monotonic()
            if override_result:
                result = override_result
                is_error = result.is_error
            else:
                try:
                    if not tool:
                        raise ValueError(f"Tool {tool_call.name} not found")

                    validated_args = _validate_tool_arguments(tool, tool_call.arguments)

                    result = await tool.execute(
                        tool_call.id,
                        validated_args,
                        signal,
                        lambda partial: stream.push(
                            AgentEvent(
                                type="tool_execution_update",
                                tool_call_id=tool_call.id,
                                tool_name=tool_call.name,
                                args=tool_call.arguments,
                                result=partial,
                            )
                        ),
                    )
                    is_error = result.is_error
                except asyncio.CancelledError:
                    aborted_result = ToolResult(
                        content=[
                            TextContent(type="text", text="Operation aborted by user.")
                        ],
                        details={"aborted": True},
                        is_error=True,
                    )
                    stream.push(
                        AgentEvent(
                            type="tool_execution_end",
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            result=aborted_result,
                            is_error=True,
                        )
                    )
                    return {
                        "tool_results": results,
                        "steering_messages": steering_messages,
                        "aborted": True,
                    }
                except Exception as err:
                    record_exception(span, err)
                    error_text = format_exception(err)
                    result = ToolResult(
                        content=[TextContent(type="text", text=error_text)],
                        details={"error": error_text},
                        is_error=True,
                    )
                    is_error = True

            modified_result = await _run_callbacks(
                hooks.after_tool, cb_ctx, tool_call.name, tool_call.arguments, result
            )
            if modified_result:
                result = modified_result
                is_error = result.is_error

            try:
                result.content = normalize_content_blocks(result.content)
            except ValueError as err:
                error_text = format_exception(err)
                result = ToolResult(
                    content=[TextContent(type="text", text=error_text)],
                    details={"error": error_text},
                    is_error=True,
                )
                is_error = True

            text_len = 0
            if result.content:
                for item in result.content:
                    if hasattr(item, "text") and item.text:
                        text_len += len(item.text)
            tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
            status = "ERROR" if is_error else "OK"
            set_span_attributes(
                span,
                {
                    "picho.duration.ms": tool_elapsed_ms,
                    "picho.status": "error" if is_error else "ok",
                    "picho.tool.output_chars": text_len,
                    "picho.tool.result_preview": preview_json(result),
                },
            )
            if not is_error:
                set_ok_status(span)
            _log.info(
                f"Tool: {tool_call.name} | {status} | {tool_elapsed_ms}ms | output={text_len} chars"
            )
            stream.push(
                AgentEvent(
                    type="tool_execution_end",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    result=result,
                    is_error=is_error,
                )
            )

            tool_result_message = ToolResultMessage(
                role="toolResult",
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=result.content,
                details=result.details,
                is_error=is_error,
            )

            results.append(tool_result_message)
            stream.push(AgentEvent(type="message_start", message=tool_result_message))
            stream.push(AgentEvent(type="message_end", message=tool_result_message))

            if get_steering_messages:
                steering = await get_steering_messages()
                if steering:
                    steering_messages = steering
                    remaining_calls = tool_calls[i + 1 :]
                    for skipped in remaining_calls:
                        results.append(_skip_tool_call(skipped, stream))
                    break

    return {"tool_results": results, "steering_messages": steering_messages}


def _skip_tool_call(
    tool_call: ToolCall,
    stream: AgentEventStream,
) -> ToolResultMessage:
    result = ToolResult(
        content=[TextContent(type="text", text="Skipped due to queued user message.")],
        details={},
        is_error=True,
    )

    _log.info(f"Tool execution skipped name={tool_call.name} id={tool_call.id}")
    stream.push(
        AgentEvent(
            type="tool_execution_start",
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            args=tool_call.arguments,
        )
    )
    stream.push(
        AgentEvent(
            type="tool_execution_end",
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            result=result,
            is_error=True,
        )
    )

    return ToolResultMessage(
        role="toolResult",
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        content=result.content,
        details={},
        is_error=True,
    )

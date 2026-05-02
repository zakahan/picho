import os
import json
import asyncio
from typing import Literal, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import contextmanager

from ..agent import Agent, AgentEvent
from ..agent.types import RunContext
from ..session import SessionManager
from ..session.raw import RawSessionWriter, raw_session_dir_for_sessions_path
from ..session.compaction import (
    CompactionSettings,
    prepare_compaction,
    generate_summary,
    estimate_context_tokens,
    extract_file_ops,
    should_compact,
)
from ..provider.types import Message
from ..skills import load_skills, Skill
from ..config import Config
from ..logger import (
    get_logger,
    set_log_dir,
    log_context,
    get_log_context,
    log_exception,
)
from ..observability import configure_observability

_log = get_logger(__name__)


@dataclass
class SessionState:
    agent: Agent
    session: SessionManager
    workspace: str
    raw_session: RawSessionWriter | None = None
    compaction_settings: CompactionSettings = field(default_factory=CompactionSettings)
    _unsubscribe: Callable[[], None] | None = field(default=None, repr=False)
    _compaction_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _auto_compaction_task: asyncio.Task | None = field(default=None, repr=False)


class Runner:
    def __init__(self, config_type: Literal["dict", "json"], config: dict | str):
        if config_type == "dict" and isinstance(config, dict):
            raw_config = config
        elif config_type == "json" and isinstance(config, str):
            if not os.path.exists(config):
                raise ValueError("config.json is not found")
            with open(config, "r", encoding="utf-8") as f:
                raw_config = json.load(f)
        else:
            raise ValueError("Unsupported configuration type")

        self._config = Config.from_dict(raw_config)
        self._normalize_paths()
        self._validate_paths()
        set_log_dir(self._config.path.logs_path)
        if self._config.observability.enabled:
            configure_observability(self._config.path.get_telemetry_dir())
        else:
            _log.info("Observability disabled by config")

        self._sessions: dict[str, SessionState] = {}
        self._skills: list[Skill] = []
        self._load_skills()
        _log.debug(f"Runner initialized with {len(self._skills)} skills")

    def _normalize_paths(self) -> None:
        def normalize(path: str | None) -> str | None:
            if not path:
                return path
            return str(Path(path).expanduser().resolve(strict=False))

        path_config = self._config.path
        path_config.base = normalize(path_config.base) or str(
            Path(os.getcwd()) / ".picho"
        )
        path_config.logs = normalize(path_config.logs)
        path_config.sessions = normalize(path_config.sessions)
        path_config.telemetry = normalize(path_config.telemetry)
        path_config.executor = normalize(path_config.executor)
        path_config.cache = normalize(path_config.cache)
        path_config.skills = [
            normalize(path) or path for path in path_config.get_skill_paths()
        ]

    def _validate_paths(self) -> None:
        self._ensure_workspace_path(self._config.path.executor_path)

    def _ensure_workspace_path(self, workspace: str) -> str:
        workspace = str(Path(workspace).expanduser().resolve(strict=False))
        workspace_path = Path(workspace)
        if not workspace_path.exists():
            raise FileNotFoundError(
                "Configured workspace does not exist: "
                f"{workspace_path}. Fix `path.executor` before starting picho."
            )
        if not workspace_path.is_dir():
            raise NotADirectoryError(
                "Configured workspace is not a directory: "
                f"{workspace_path}. Fix `path.executor` before starting picho."
            )
        return workspace

    def _build_agent_instructions(self, workspace: str) -> str:
        instructions = self._config.agent.instructions
        default_workspace = self._config.path.executor_path
        if (
            default_workspace
            and default_workspace in instructions
            and workspace != default_workspace
        ):
            return instructions.replace(default_workspace, workspace)
        return instructions

    @contextmanager
    def _session_log_context(self, session_id: str):
        state = self._sessions.get(session_id)
        session_file = state.session.get_session_file() if state else None
        workspace = state.workspace if state else self._config.path.executor_path
        with log_context(
            session_id=session_id,
            session_file=session_file,
            workspace=workspace,
        ):
            yield

    def _load_skills(self) -> None:
        from ..builtin.skill import load_builtin_skills

        builtin_skill_names = self._config.agent.builtin.skill
        custom_skill_paths = self._config.path.get_skill_paths()

        all_skills = []
        all_diagnostics = []

        if builtin_skill_names:
            builtin_result = load_builtin_skills(skill_names=builtin_skill_names)
            all_skills.extend(builtin_result.skills)
            all_diagnostics.extend(builtin_result.diagnostics)

        if custom_skill_paths:
            result = load_skills(
                cwd=self._config.path.base,
                skill_paths=custom_skill_paths,
                include_defaults=True,
            )
            all_skills.extend(result.skills)
            all_diagnostics.extend(result.diagnostics)
        elif not builtin_skill_names:
            result = load_skills(
                cwd=self._config.path.base,
                skill_paths=None,
                include_defaults=True,
            )
            all_skills.extend(result.skills)
            all_diagnostics.extend(result.diagnostics)

        self._skills = all_skills

        for diag in all_diagnostics:
            if diag.type == "warning":
                _log.warning(f"Skill loading: {diag.message} ({diag.path})")
            elif diag.type == "error":
                _log.error(f"Skill loading: {diag.message} ({diag.path})")

    def get_skills(self) -> list[Skill]:
        return self._skills

    def get_skill(self, name: str) -> Skill | None:
        for skill in self._skills:
            if skill.name == name:
                return skill
        return None

    def _create_agent(self, workspace: str | None = None) -> Agent:
        from ..provider import get_model

        acfg = self._config.agent
        effective_workspace = self._ensure_workspace_path(
            workspace or self._config.path.executor_path
        )

        tools = []
        builtin_tool_names = acfg.builtin.tool
        custom_tool_specs = acfg.tools
        if builtin_tool_names or custom_tool_specs:
            from ..tool.executor import create_executor

            executor_env = (
                acfg.executor.env
                if hasattr(acfg, "executor") and acfg.executor.env
                else None
            )
            executor = create_executor(
                cwd=effective_workspace,
                env=executor_env,
            )
            env_path = (
                acfg.executor.env_path
                if hasattr(acfg, "executor") and acfg.executor.env_path
                else None
            )
            init_command = (
                acfg.executor.init_command
                if hasattr(acfg, "executor") and acfg.executor.init_command
                else None
            )

            if builtin_tool_names:
                from ..builtin.tool import create_builtin_tools

                all_builtin_tools = create_builtin_tools(
                    executor,
                    env_path=env_path,
                    init_command=init_command,
                    read_config=acfg.builtin.tool_config.read,
                    cache_root=self._config.path.cache_path,
                )

                tool_map = {tool.name: tool for tool in all_builtin_tools}
                for name in builtin_tool_names:
                    if name in tool_map:
                        tools.append(tool_map[name])

            if custom_tool_specs:
                from ..tool import ToolFactoryContext, load_custom_tools

                custom_tools = load_custom_tools(
                    custom_tool_specs,
                    ToolFactoryContext(
                        workspace=effective_workspace,
                        cache_root=self._config.path.cache_path,
                        config=self._config,
                        executor=executor,
                    ),
                )
                tools.extend(custom_tools)

            self._validate_unique_tool_names(tools)

            _log.debug(f"Created {len(tools)} tools with cwd={effective_workspace}")

        agent = Agent(
            model=get_model(
                model_provider=acfg.model.model_provider,
                model_name=acfg.model.model_name,
                base_url=acfg.model.base_url,
                api_key=acfg.model.api_key,
                input_types=acfg.model.input_types,
            ),
            instructions=self._build_agent_instructions(effective_workspace),
            thinking_level=acfg.thinking_level,
            tools=tools,
            steering_mode=acfg.steering_mode,
            follow_up_mode=acfg.follow_up_mode,
            skills=self._skills,
            skill_paths=self._config.path.get_skill_paths(),
        )

        return agent

    def _validate_unique_tool_names(self, tools: list[Any]) -> None:
        seen: set[str] = set()
        duplicates: list[str] = []
        for tool in tools:
            if tool.name in seen:
                duplicates.append(tool.name)
            seen.add(tool.name)
        if duplicates:
            names = ", ".join(sorted(set(duplicates)))
            raise ValueError(f"Duplicate tool names are not allowed: {names}")

    def _create_session_manager(
        self, session_file: str | None = None
    ) -> SessionManager:
        scfg = self._config.session

        session_manager = SessionManager(
            cwd=self._config.path.sessions_path,
            persist=scfg.persist,
            session_file=session_file,
        )
        return session_manager

    def _get_compaction_settings(self) -> CompactionSettings:
        ccfg = self._config.agent.compaction
        return CompactionSettings(
            enabled=ccfg.enabled,
            reserve_tokens=ccfg.reserve_tokens,
            keep_recent_tokens=ccfg.keep_recent_tokens,
            trigger_threshold=ccfg.trigger_threshold,
        )

    def _subscribe_agent(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if not state:
            return

        def on_event(event: AgentEvent) -> None:
            self._on_agent_event(session_id, event)

        state._unsubscribe = state.agent.subscribe(on_event)

    def _sync_agent_messages_from_session(self, state: SessionState) -> None:
        state.agent.replace_messages(list(state.session.get_context().messages))

    def _restore_agent_from_session(self, state: SessionState) -> None:
        self._sync_agent_messages_from_session(state)

    def _build_run_context(self, session_id: str, state: SessionState) -> RunContext:
        run_state: dict[str, Any] = {}
        if state.raw_session:
            run_state["on_payload"] = self._build_raw_payload_callback(
                session_id, state
            )
        return RunContext(
            # Keep a stable agent identity for callbacks/logging and future multi-agent flows.
            agent_name="agent",
            session_id=session_id,
            session_file=state.session.get_session_file() or "",
            workspace=state.workspace,
            state=run_state,
        )

    def _build_raw_payload_callback(
        self, session_id: str, state: SessionState
    ) -> Callable[[dict[str, Any], Any], None]:
        def on_payload(payload: dict[str, Any], model: Any) -> None:
            if not state.raw_session:
                return
            try:
                state.raw_session.write_model_request(
                    session_id=session_id,
                    invocation_id=get_log_context().get("invocation_id", ""),
                    provider=getattr(model, "model_provider", ""),
                    model=getattr(model, "model_name", ""),
                    payload=payload,
                )
            except Exception as error:
                log_exception(_log, "Raw session write failed", error)

        return on_payload

    def _create_raw_session_writer(
        self, session: SessionManager
    ) -> RawSessionWriter | None:
        if not self._config.debug.raw_session:
            return None
        session_file = session.get_session_file()
        if not session_file:
            return None
        raw_dir = raw_session_dir_for_sessions_path(str(Path(session_file).parent))
        return RawSessionWriter(session_file=session_file, raw_session_dir=raw_dir)

    def _on_agent_event(self, session_id: str, event: AgentEvent) -> None:
        state = self._sessions.get(session_id)
        if not state:
            return

        if event.type == "message_end" and event.message:
            state.session.append_message(event.message)
        elif event.type == "agent_end":
            self._check_auto_compaction(session_id)

    def _check_auto_compaction(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if not state or not state.compaction_settings.enabled:
            return

        if state._auto_compaction_task and not state._auto_compaction_task.done():
            return

        state._auto_compaction_task = asyncio.create_task(
            self._auto_compaction_check(session_id)
        )

    async def _auto_compaction_check(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if not state:
            return

        async with state._compaction_lock:
            try:
                context = state.session.get_context()
                tokens = estimate_context_tokens(context.messages)

                model = state.agent.state.model
                context_window = (
                    getattr(model, "context_window", 128000) if model else 128000
                )

                if should_compact(tokens, context_window, state.compaction_settings):
                    _log.debug(f"Auto compaction triggered for session {session_id}")
                    await self._run_compaction(session_id)
            except Exception as e:
                log_exception(
                    _log, "Auto compaction check failed", e, session_id=session_id
                )

    async def _run_compaction(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if not state:
            return

        entries = state.session.get_entries()
        preparation = prepare_compaction(entries, state.compaction_settings)

        if not preparation:
            return

        model = state.agent.state.model
        if not model:
            return

        summary = await generate_summary(
            preparation.messages_to_summarize,
            model,
        )

        file_ops = extract_file_ops(preparation.messages_to_summarize)

        state.session.append_compaction(
            summary=summary,
            first_kept_entry_id=preparation.first_kept_entry_id,
            tokens_before=preparation.tokens_before,
            details=file_ops,
        )
        self._sync_agent_messages_from_session(state)

    def create_session(self, session_id: str | None = None) -> str:
        workspace = self._config.path.executor_path
        agent = self._create_agent(workspace=workspace)
        session = self._create_session_manager()
        compaction_settings = self._get_compaction_settings()

        sid = session_id or session.get_session_id()

        if sid in self._sessions:
            raise ValueError(f"Session {sid} already exists")

        state = SessionState(
            agent=agent,
            session=session,
            workspace=workspace,
            raw_session=self._create_raw_session_writer(session),
            compaction_settings=compaction_settings,
        )
        self._sessions[sid] = state
        self._subscribe_agent(sid)

        with self._session_log_context(sid):
            _log.info(
                "Session created | "
                f"id={sid} file={session.get_session_file()} cwd={session.cwd}"
            )
        return sid

    def load_session(self, session_file: str, session_id: str | None = None) -> str:
        workspace = self._config.path.executor_path
        agent = self._create_agent(workspace=workspace)
        session = self._create_session_manager(session_file)
        compaction_settings = self._get_compaction_settings()

        sid = session_id or session.get_session_id()

        if sid in self._sessions:
            raise ValueError(f"Session {sid} already exists")

        state = SessionState(
            agent=agent,
            session=session,
            workspace=workspace,
            raw_session=self._create_raw_session_writer(session),
            compaction_settings=compaction_settings,
        )
        self._restore_agent_from_session(state)
        self._sessions[sid] = state
        self._subscribe_agent(sid)

        with self._session_log_context(sid):
            _log.info(f"Session loaded | id={sid} file={session_file}")
        return sid

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def get_agent(self, session_id: str) -> Agent | None:
        state = self._sessions.get(session_id)
        return state.agent if state else None

    def get_session_manager(self, session_id: str) -> SessionManager | None:
        state = self._sessions.get(session_id)
        return state.session if state else None

    def get_session_workspace(self, session_id: str) -> str | None:
        state = self._sessions.get(session_id)
        return state.workspace if state else None

    def set_session_workspace(self, session_id: str, workspace: str) -> str:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        normalized_workspace = self._ensure_workspace_path(workspace)
        if normalized_workspace == state.workspace:
            return normalized_workspace

        if state.agent.state.is_streaming:
            raise ValueError(f"Session {session_id} is currently streaming")

        if state._unsubscribe:
            state._unsubscribe()
            state._unsubscribe = None

        state.agent.abort()
        state.agent = self._create_agent(workspace=normalized_workspace)
        state.workspace = normalized_workspace
        self._restore_agent_from_session(state)
        self._subscribe_agent(session_id)
        _log.info(
            f"Session workspace switched | id={session_id} workspace={normalized_workspace}"
        )
        return normalized_workspace

    @property
    def config(self) -> Config:
        return self._config

    def delete_session(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if not state:
            return False

        if state._unsubscribe:
            state._unsubscribe()

        if state._auto_compaction_task and not state._auto_compaction_task.done():
            state._auto_compaction_task.cancel()

        del self._sessions[session_id]
        _log.debug(f"Deleted session: {session_id}")
        return True

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def list_sessions(self) -> list[dict[str, Any]]:
        result = []
        for sid, state in self._sessions.items():
            header = state.session.get_header()
            result.append(
                {
                    "session_id": sid,
                    "session_file": state.session.get_session_file(),
                    "cwd": state.session.get_cwd(),
                    "workspace": state.workspace,
                    "entry_count": len(state.session.get_entries()),
                    "leaf_id": state.session.get_leaf_id(),
                    "created": header.timestamp if header else None,
                }
            )
        return result

    def list_persisted_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        temp_session = self._create_session_manager()
        sessions = temp_session.list_sessions()

        result = []
        for s in sessions:
            result.append(
                {
                    "session_id": s.id,
                    "session_file": s.path,
                    "cwd": s.cwd,
                    "created": s.created.isoformat() if s.created else None,
                    "modified": s.modified.isoformat() if s.modified else None,
                    "message_count": s.message_count,
                    "first_message": s.first_message,
                }
            )

        if limit:
            result = result[:limit]
        return result

    def get_active_session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def close_all(self) -> None:
        for session_id in list(self._sessions.keys()):
            self.delete_session(session_id)
        _log.debug("Closed all sessions")

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    async def prompt(
        self, session_id: str, message: str | Message | list[Message]
    ) -> None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        with self._session_log_context(session_id):
            _log.debug(f"Prompting session {session_id}")
            await state.agent.prompt(
                message,
                run_context=self._build_run_context(session_id, state),
            )

    async def continue_(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        with self._session_log_context(session_id):
            await state.agent.continue_(
                run_context=self._build_run_context(session_id, state),
            )

    def abort(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state:
            state.agent.abort()
            _log.warning(f"Aborted session: {session_id}")

    def is_streaming(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if not state:
            return False
        return state.agent.state.is_streaming

    def steer(self, session_id: str, message: str | Message | list[Message]) -> None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        from ..provider.types import UserMessage, TextContent, Message

        messages: list[Message]
        if isinstance(message, list):
            messages = message
        elif isinstance(message, str):
            messages = [UserMessage(content=[TextContent(type="text", text=message)])]
        else:
            messages = [message]

        with self._session_log_context(session_id):
            for msg in messages:
                state.agent.steer(msg)
            _log.debug(f"Steered session {session_id} with {len(messages)} message(s)")

    def follow_up(
        self, session_id: str, message: str | Message | list[Message]
    ) -> None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        from ..provider.types import UserMessage, TextContent, Message

        messages: list[Message]
        if isinstance(message, list):
            messages = message
        elif isinstance(message, str):
            messages = [UserMessage(content=[TextContent(type="text", text=message)])]
        else:
            messages = [message]

        with self._session_log_context(session_id):
            for msg in messages:
                state.agent.follow_up(msg)
            _log.debug(
                f"Follow-up queued for session {session_id} with {len(messages)} message(s)"
            )

    def has_queued_messages(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if not state:
            return False
        return state.agent.has_queued_messages()

    def reset(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state:
            state.agent.reset()
            state.session.new_session()
            _log.debug(f"Reset session: {session_id}")

    def subscribe(
        self, session_id: str, listener: Callable[[AgentEvent], None]
    ) -> Callable[[], None]:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        return state.agent.subscribe(listener)

    def branch(self, session_id: str, from_entry_id: str | None = None) -> str:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        new_session_file = state.session.branch(from_entry_id)
        new_session = SessionManager(
            cwd=state.session.get_cwd(),
            session_file=new_session_file,
        )

        new_agent = self._create_agent(workspace=state.workspace)

        new_sid = new_session.get_session_id()
        new_state = SessionState(
            agent=new_agent,
            session=new_session,
            workspace=state.workspace,
            raw_session=self._create_raw_session_writer(new_session),
            compaction_settings=self._get_compaction_settings(),
        )
        self._restore_agent_from_session(new_state)
        self._sessions[new_sid] = new_state
        self._subscribe_agent(new_sid)

        _log.debug(f"Branched session: {session_id} -> {new_sid}")
        return new_sid

    def goto(self, session_id: str, entry_id: str | None) -> None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        state.session.goto(entry_id)

        self._restore_agent_from_session(state)

        _log.debug(f"Goto entry: {entry_id} in session {session_id}")

    async def manual_compact(self, session_id: str) -> str | None:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        async with state._compaction_lock:
            entries = state.session.get_entries()
            preparation = prepare_compaction(entries, state.compaction_settings)

            if not preparation:
                return None

            model = state.agent.state.model
            if not model:
                return None

            summary = await generate_summary(
                preparation.messages_to_summarize,
                model,
            )

            file_ops = extract_file_ops(preparation.messages_to_summarize)

            state.session.append_compaction(
                summary=summary,
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
                details=file_ops,
            )
            self._sync_agent_messages_from_session(state)

            _log.debug(f"Manual compaction completed for session {session_id}")
            return summary

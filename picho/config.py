"""
Configuration for picho

Centralized configuration management with a clean tree structure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


def _default_base() -> str:
    return str(Path(os.getcwd()) / ".picho")


@dataclass
class ModelConfig:
    model_provider: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    input_types: list[str] = field(default_factory=lambda: ["text"])

    @classmethod
    def from_dict(cls, data: dict | None) -> "ModelConfig":
        if data is None:
            return cls()
        return cls(
            model_provider=data.get("model_provider"),
            model_name=data.get("model_name"),
            base_url=data.get("base_url"),
            api_key=data.get("api_key"),
            input_types=data.get("input_types", ["text"]),
        )


@dataclass
class BuiltinConfig:
    tool: list[str] = field(default_factory=lambda: ["read", "write", "bash", "edit"])
    skill: list[str] = field(
        default_factory=lambda: ["code-review", "debug", "skill-creator"]
    )
    tool_config: "ToolConfig" = field(default_factory=lambda: ToolConfig())

    @classmethod
    def from_dict(cls, data: dict | None) -> "BuiltinConfig":
        if data is None:
            return cls()
        return cls(
            tool=data.get("tool", ["read", "write", "bash", "edit"]),
            skill=data.get("skill", ["code-review", "debug", "skill-creator"]),
            tool_config=ToolConfig.from_dict(data.get("tool_config")),
        )


@dataclass
class ReadVideoCompressionConfig:
    enabled: bool = True
    trigger_size_mb: int = 512

    @property
    def trigger_size_bytes(self) -> int:
        return self.trigger_size_mb * 1024 * 1024

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadVideoCompressionConfig":
        if data is None:
            return cls()
        return cls(
            enabled=data.get("enabled", True),
            trigger_size_mb=data.get("trigger_size_mb", 512),
        )


@dataclass
class ReadVolcengineAsrConfig:
    tos_bucket: str | None = None
    tos_bucket_env: str = "DEFAULT_TOS_BUCKET"
    tos_region: str = "cn-beijing"
    tos_access_key_env: str = "VOLCENGINE_ACCESS_KEY"
    tos_secret_key_env: str = "VOLCENGINE_SECRET_KEY"
    speech_api_key_env: str = "VOLCENGINE_SPEECH_API_KEY"
    sample_rate: int = 16000
    channel: int = 1
    codec: Literal["raw", "opus"] = "raw"

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadVolcengineAsrConfig":
        if data is None:
            return cls()
        return cls(
            tos_bucket=data.get("tos_bucket"),
            tos_bucket_env=data.get("tos_bucket_env", "DEFAULT_TOS_BUCKET"),
            tos_region=data.get("tos_region", "cn-beijing"),
            tos_access_key_env=data.get("tos_access_key_env", "VOLCENGINE_ACCESS_KEY"),
            tos_secret_key_env=data.get("tos_secret_key_env", "VOLCENGINE_SECRET_KEY"),
            speech_api_key_env=data.get(
                "speech_api_key_env", "VOLCENGINE_SPEECH_API_KEY"
            ),
            sample_rate=data.get("sample_rate", 16000),
            channel=data.get("channel", 1),
            codec=data.get("codec", "raw"),
        )


@dataclass
class ReadAudioAsrConfig:
    provider: Literal["mock", "volcengine"] = "mock"
    language: str | None = None
    enable_punc: bool = False
    enable_itn: bool = True
    enable_ddc: bool = False
    enable_speaker_info: bool = False
    include_utterances: bool = True
    include_words: bool = False
    vad_segment: bool = False
    timeout_seconds: int = 60
    poll_interval_seconds: int = 2
    volcengine: ReadVolcengineAsrConfig = field(default_factory=ReadVolcengineAsrConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadAudioAsrConfig":
        if data is None:
            return cls()
        return cls(
            provider=data.get("provider", "mock"),
            language=data.get("language"),
            enable_punc=data.get("enable_punc", False),
            enable_itn=data.get("enable_itn", True),
            enable_ddc=data.get("enable_ddc", False),
            enable_speaker_info=data.get("enable_speaker_info", False),
            include_utterances=data.get("include_utterances", True),
            include_words=data.get("include_words", False),
            vad_segment=data.get("vad_segment", False),
            timeout_seconds=data.get("timeout_seconds", 60),
            poll_interval_seconds=data.get("poll_interval_seconds", 2),
            volcengine=ReadVolcengineAsrConfig.from_dict(data.get("volcengine")),
        )


@dataclass
class ReadToolConfig:
    extensions: list[str] = field(default_factory=list)
    video_compression: ReadVideoCompressionConfig = field(
        default_factory=ReadVideoCompressionConfig
    )
    audio_asr: ReadAudioAsrConfig = field(default_factory=ReadAudioAsrConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadToolConfig":
        if data is None:
            return cls()
        return cls(
            extensions=data.get("extensions", []),
            video_compression=ReadVideoCompressionConfig.from_dict(
                data.get("video_compression")
            ),
            audio_asr=ReadAudioAsrConfig.from_dict(data.get("audio_asr")),
        )


@dataclass
class ToolConfig:
    read: ReadToolConfig = field(default_factory=ReadToolConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ToolConfig":
        if data is None:
            return cls()
        return cls(
            read=ReadToolConfig.from_dict(data.get("read")),
        )


@dataclass
class CompactionConfig:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000
    trigger_threshold: int = 100000

    @classmethod
    def from_dict(cls, data: dict | None) -> "CompactionConfig":
        if data is None:
            return cls()
        return cls(
            enabled=data.get("enabled", True),
            reserve_tokens=data.get("reserve_tokens", 16384),
            keep_recent_tokens=data.get("keep_recent_tokens", 20000),
            trigger_threshold=data.get("trigger_threshold", 100000),
        )


@dataclass
class ExecutorConfig:
    env_path: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    init_command: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "ExecutorConfig":
        if data is None:
            return cls()
        return cls(
            env_path=data.get("env_path") if data else None,
            env=data.get("env", {}) if data else {},
            init_command=data.get("init_command") if data else None,
        )


@dataclass
class AgentConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    instructions: str = "You are a helpful AI assistant named picho."
    instructions_files: list[str] = field(default_factory=list)
    thinking_level: Literal["auto", "enabled", "disabled"] = "auto"
    builtin: BuiltinConfig = field(default_factory=BuiltinConfig)
    tools: list[str] = field(default_factory=list)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    steering_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    follow_up_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AgentConfig":
        if data is None:
            return cls()

        raw_instructions = data.get("instructions")
        raw_instructions_files = data.get("instructions_files")

        if raw_instructions is not None and raw_instructions_files is not None:
            raise ValueError(
                "'instructions' and 'instructions_files' are mutually exclusive; "
                "use one or the other, not both."
            )

        if raw_instructions_files is not None:
            instructions = ""
            instructions_files = raw_instructions_files
        else:
            instructions = (
                raw_instructions or "You are a helpful AI assistant named picho."
            )
            instructions_files = []

        return cls(
            model=ModelConfig.from_dict(data.get("model")),
            instructions=instructions,
            instructions_files=instructions_files,
            thinking_level=data.get("thinking_level", "auto"),
            builtin=BuiltinConfig.from_dict(data.get("builtin")),
            tools=data.get("tools", []),
            compaction=CompactionConfig.from_dict(data.get("compaction")),
            steering_mode=data.get("steering_mode", "one-at-a-time"),
            follow_up_mode=data.get("follow_up_mode", "one-at-a-time"),
            executor=ExecutorConfig.from_dict(data.get("executor")),
        )


@dataclass
class SessionConfig:
    persist: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "SessionConfig":
        if data is None:
            return cls()
        return cls(
            persist=data.get("persist", True),
        )


@dataclass
class ObservabilityConfig:
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "ObservabilityConfig":
        if data is None:
            return cls()
        return cls(
            enabled=data.get("enabled", True),
        )


@dataclass
class DebugConfig:
    raw_session: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "DebugConfig":
        if data is None:
            return cls()
        return cls(
            raw_session=data.get("raw_session", False),
        )


@dataclass
class PathConfig:
    base: str = ""
    logs: str | None = None
    sessions: str | None = None
    telemetry: str | None = None
    executor: str | None = None
    cache: str | None = None
    skills: list[str] = field(default_factory=lambda: ["skills"])

    @classmethod
    def from_dict(
        cls, data: dict | str | None, legacy_cwd: str | None = None
    ) -> "PathConfig":
        if data is None:
            if legacy_cwd:
                return cls(base=str(Path(legacy_cwd) / ".picho"), executor=legacy_cwd)
            return cls(base=_default_base())

        if isinstance(data, str):
            return cls(base=data)

        base = data.get("base")
        if not base and legacy_cwd:
            base = str(Path(legacy_cwd) / ".picho")
        base = base or _default_base()
        return cls(
            base=base,
            logs=data.get("logs"),
            sessions=data.get("sessions"),
            telemetry=data.get("telemetry"),
            executor=data.get("executor") or legacy_cwd,
            cache=data.get("cache"),
            skills=data.get("skills", ["skills"]),
        )

    @property
    def logs_path(self) -> str:
        return self.logs or str(Path(self.base) / "logs")

    @property
    def sessions_path(self) -> str:
        return self.sessions or str(Path(self.base) / "sessions")

    @property
    def telemetry_path(self) -> str:
        return self.telemetry or str(Path(self.base) / "telemetry")

    @property
    def executor_path(self) -> str:
        return self.executor or os.getcwd()

    @property
    def cache_path(self) -> str:
        return self.cache or str(Path(self.base) / "caches")

    def get_skill_paths(self) -> list[str]:
        result = []
        for path in self.skills:
            expanded = os.path.expanduser(path)
            if os.path.isabs(expanded):
                result.append(expanded)
            else:
                result.append(os.path.join(self.base, expanded))
        return result

    def get_log_dir(self) -> str:
        return self.logs_path

    def get_session_dir(self) -> str:
        return self.sessions_path

    def get_telemetry_dir(self) -> str:
        return self.telemetry_path


@dataclass
class Config:
    path: PathConfig = field(default_factory=PathConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        legacy_cwd = data.get("session_manager", {}).get("cwd")

        return cls(
            path=PathConfig.from_dict(data.get("path"), legacy_cwd),
            agent=AgentConfig.from_dict(data.get("agent")),
            session=SessionConfig.from_dict(data.get("session_manager")),
            observability=ObservabilityConfig.from_dict(data.get("observability")),
            debug=DebugConfig.from_dict(data.get("debug")),
        )

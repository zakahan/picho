"""
Configuration for picho

Centralized configuration management with a clean tree structure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


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
class ReadToolConfig:
    extensions: list[str] = field(default_factory=list)
    video_compression: ReadVideoCompressionConfig = field(
        default_factory=ReadVideoCompressionConfig
    )

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadToolConfig":
        if data is None:
            return cls()
        return cls(
            extensions=data.get("extensions", []),
            video_compression=ReadVideoCompressionConfig.from_dict(
                data.get("video_compression")
            ),
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
    thinking_level: Literal["auto", "enabled", "disabled"] = "auto"
    builtin: BuiltinConfig = field(default_factory=BuiltinConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    steering_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    follow_up_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AgentConfig":
        if data is None:
            return cls()
        return cls(
            model=ModelConfig.from_dict(data.get("model")),
            instructions=data.get(
                "instructions", "You are a helpful AI assistant named picho."
            ),
            thinking_level=data.get("thinking_level", "auto"),
            builtin=BuiltinConfig.from_dict(data.get("builtin")),
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
class PathConfig:
    base: str = ""
    logs: str | None = None
    sessions: str | None = None
    telemetry: str | None = None
    executor: str | None = None
    cache: str | None = None
    skills: list[str] = field(default_factory=lambda: [".picho/skills"])

    @classmethod
    def from_dict(
        cls, data: dict | str | None, legacy_cwd: str | None = None
    ) -> "PathConfig":
        if data is None:
            base = legacy_cwd or os.getcwd()
            return cls(base=base)

        if isinstance(data, str):
            return cls(base=data)

        base = data.get("base") or legacy_cwd or os.getcwd()
        return cls(
            base=base,
            logs=data.get("logs"),
            sessions=data.get("sessions"),
            telemetry=data.get("telemetry"),
            executor=data.get("executor"),
            cache=data.get("cache"),
            skills=data.get("skills", [".picho/skills"]),
        )

    @property
    def logs_path(self) -> str:
        return self.logs or self.base

    @property
    def sessions_path(self) -> str:
        return self.sessions or self.base

    @property
    def telemetry_path(self) -> str:
        return self.telemetry or self.base

    @property
    def executor_path(self) -> str:
        return self.executor or self.base

    @property
    def cache_path(self) -> str:
        if not self.cache:
            return self.base

        expanded = os.path.expanduser(self.cache)
        if os.path.isabs(expanded):
            return expanded
        return str(Path(self.base) / expanded)

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
        return str(Path(self.logs_path) / ".picho" / "logs")

    def get_session_dir(self) -> str:
        return str(Path(self.sessions_path) / ".picho" / "sessions")

    def get_telemetry_dir(self) -> str:
        return str(Path(self.telemetry_path) / ".picho" / "telemetry")


@dataclass
class Config:
    path: PathConfig = field(default_factory=PathConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        legacy_cwd = data.get("session_manager", {}).get("cwd")

        return cls(
            path=PathConfig.from_dict(data.get("path"), legacy_cwd),
            agent=AgentConfig.from_dict(data.get("agent")),
            session=SessionConfig.from_dict(data.get("session_manager")),
            observability=ObservabilityConfig.from_dict(data.get("observability")),
        )

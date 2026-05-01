"""
CLI configuration for picho
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


ToolDisplayLevel = Literal["off", "low", "all"]
DisplayThemeName = Literal["default", "dark", "light", "ocean", "forest", "mono"]


@dataclass
class ChatConfig:
    show_thinking: bool = True
    show_tool_execution: bool = True
    show_tool_args: ToolDisplayLevel = "off"
    show_tool_result: ToolDisplayLevel = "off"
    stream_output: bool = True
    prompt_prefix: str = "You"
    assistant_name: str = "picho"


@dataclass
class DisplayConfig:
    theme: DisplayThemeName = "default"
    color_enabled: bool = True
    show_banner: bool = True
    show_usage: bool = True


@dataclass
class LogConfig:
    console_output: bool = False


@dataclass
class CLIConfig:
    chat: ChatConfig = field(default_factory=ChatConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    log: LogConfig = field(default_factory=LogConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "CLIConfig":
        chat_data = data.get("chat", {})
        display_data = data.get("display", {})
        log_data = data.get("log", {})

        return cls(
            chat=ChatConfig(
                show_thinking=chat_data.get("show_thinking", True),
                show_tool_execution=chat_data.get("show_tool_execution", True),
                show_tool_args=chat_data.get("show_tool_args", "off"),
                show_tool_result=chat_data.get("show_tool_result", "off"),
                stream_output=chat_data.get("stream_output", True),
                prompt_prefix=chat_data.get("prompt_prefix", "You"),
                assistant_name=chat_data.get("assistant_name", "picho"),
            ),
            display=DisplayConfig(
                theme=display_data.get("theme", "default"),
                color_enabled=display_data.get("color_enabled", True),
                show_banner=display_data.get("show_banner", True),
                show_usage=display_data.get("show_usage", True),
            ),
            log=LogConfig(
                console_output=log_data.get("console_output", False),
            ),
        )

    @classmethod
    def default(cls) -> "CLIConfig":
        return cls()

    def to_dict(self) -> dict:
        return {
            "chat": {
                "show_thinking": self.chat.show_thinking,
                "show_tool_execution": self.chat.show_tool_execution,
                "show_tool_args": self.chat.show_tool_args,
                "show_tool_result": self.chat.show_tool_result,
                "stream_output": self.chat.stream_output,
                "prompt_prefix": self.chat.prompt_prefix,
                "assistant_name": self.chat.assistant_name,
            },
            "display": {
                "theme": self.display.theme,
                "color_enabled": self.display.color_enabled,
                "show_banner": self.display.show_banner,
                "show_usage": self.display.show_usage,
            },
            "log": {
                "console_output": self.log.console_output,
            },
        }


def get_cli_config_path() -> Path:
    cwd = Path.cwd()
    return cwd / ".picho" / "tui.json"


def get_cli_config_fallback_path() -> Path:
    return Path.home() / ".picho" / "tui.json"


def find_cli_config_path(explicit_path: str | None = None) -> Path | None:
    """Find the active TUI config path.

    Search order:
    1. CLI ``--tui-config`` explicit path
    2. Project-local ``.picho/tui.json``
    3. User-global ``~/.picho/tui.json``
    """
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if p.exists():
            return p
    for path in (get_cli_config_path(), get_cli_config_fallback_path()):
        if path.exists():
            return path
    return None


def load_cli_config(explicit_path: str | None = None) -> CLIConfig:
    config_path = find_cli_config_path(explicit_path)

    if config_path and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CLIConfig.from_dict(data)
        except Exception:
            return CLIConfig.default()
    else:
        config = CLIConfig.default()
        save_cli_config(config, explicit_path=explicit_path)
        return config


def save_cli_config(config: CLIConfig, *, explicit_path: str | None = None) -> None:
    config_path = find_cli_config_path(explicit_path) or get_cli_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)


def format_for_display(text: str, level: ToolDisplayLevel, max_chars: int = 15) -> str:
    if level == "off":
        return ""
    if level == "low":
        escaped = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        if len(escaped) > max_chars:
            return escaped[:max_chars] + "..."
        return escaped
    if len(text) > max_chars:
        return text[:max_chars] + f"... ({len(text) - max_chars} more chars)"
    return text

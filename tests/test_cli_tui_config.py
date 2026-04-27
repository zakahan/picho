from __future__ import annotations

from picho.agent.types import AgentEvent
from picho.cli.config import CLIConfig
from picho.cli.tui import ChatApp, ansi, resolve_theme
from picho.provider.types import AssistantMessage, TextContent, Usage


class _FakeRunner:
    def __init__(self) -> None:
        self.listener = None

    def get_session(self, _session_id: str):
        return None

    def is_streaming(self, _session_id: str) -> bool:
        return False

    def has_queued_messages(self, _session_id: str) -> bool:
        return False

    def subscribe(self, _session_id: str, listener):
        self.listener = listener
        return lambda: None

    def abort(self, _session_id: str) -> None:
        return None


def test_cli_config_round_trip_includes_new_display_fields():
    config = CLIConfig.from_dict(
        {
            "chat": {
                "assistant_name": "coder",
                "prompt_prefix": "me",
                "stream_output": False,
            },
            "display": {
                "theme": "ocean",
                "color_enabled": False,
                "show_banner": False,
                "show_usage": False,
            },
        }
    )

    data = config.to_dict()

    assert data["display"]["theme"] == "ocean"
    assert data["display"]["color_enabled"] is False
    assert data["display"]["show_banner"] is False
    assert data["display"]["show_usage"] is False
    assert data["chat"]["prompt_prefix"] == "me"
    assert data["chat"]["stream_output"] is False


def test_chat_app_uses_prompt_prefix_and_color_toggle():
    runner = _FakeRunner()
    config = CLIConfig.from_dict(
        {
            "chat": {
                "assistant_name": "bot",
                "prompt_prefix": "Me",
            },
            "display": {
                "theme": "mono",
                "color_enabled": False,
            },
        }
    )

    app = ChatApp(runner, "session-1", config)
    prompt = app._input_prompt()
    status = app._build_status_fragments()

    assert prompt[0][1] == "Me › "
    assert prompt[0][0] == "bold"
    assert status[1][1] == "bot"
    assert resolve_theme("mono").response_border != resolve_theme("default").response_border
    assert ansi("plain", resolve_theme("mono").gold, bold=True) == "plain"


def test_stream_output_false_renders_only_final_message(monkeypatch):
    runner = _FakeRunner()
    config = CLIConfig.from_dict(
        {
            "chat": {
                "stream_output": False,
            },
            "display": {
                "show_usage": False,
            },
        }
    )
    app = ChatApp(runner, "session-1", config)
    output: list[str] = []
    monkeypatch.setattr(app, "_emit", output.append)

    app._subscribe_current()
    assert runner.listener is not None

    runner.listener(
        AgentEvent(
            type="content_delta",
            assistant_event=type("AssistantEvent", (), {"data": type("Data", (), {"delta": "hel"})()})(),
        )
    )
    assert output == []

    runner.listener(
        AgentEvent(
            type="message_end",
            message=AssistantMessage(
                content=[TextContent(text="hello world")],
                usage=Usage(input_tokens=10, output_tokens=5),
            ),
        )
    )

    joined = "\n".join(output)
    assert "hello world" in joined
    assert "tokens in=10 out=5" not in joined

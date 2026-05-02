from __future__ import annotations

import asyncio
from pathlib import Path

from picho.runner import Runner


def test_runner_create_session_without_api_key_uses_mock_provider(tmp_path: Path):
    config = {
        "path": {
            "base": str(tmp_path),
            "logs": str(tmp_path),
            "sessions": str(tmp_path),
            "executor": str(tmp_path),
            "cache": str(tmp_path),
            "skills": [],
        },
        "agent": {
            "model": {
                "model_provider": "mock",
                "model_name": "mock-model",
                "input_types": ["text"],
            },
            "builtin": {
                "tool": [],
                "skill": [],
                "tool_config": {
                    "read": {
                        "extensions": [],
                        "video_compression": {
                            "enabled": True,
                            "trigger_size_mb": 512,
                        },
                    }
                },
            },
        },
        "session_manager": {
            "persist": True,
        },
    }

    runner = Runner(config_type="dict", config=config)
    session_id = runner.create_session()
    state = runner.get_session(session_id)

    assert runner.has_session(session_id) is True
    assert state is not None
    assert state.agent.state.model is not None
    assert state.agent.state.model.model_provider == "mock"

    session_file = state.session.get_session_file()
    assert session_file is not None
    assert Path(session_file).exists()


def test_runner_mounts_custom_tool_factory(tmp_path: Path):
    factory_path = tmp_path / "custom_tools.py"
    factory_path.write_text(
        """
from picho.builtin import pi_tool


def create_tools(context):
    @pi_tool(name="workspace_echo")
    def workspace_echo(message: str) -> str:
        return f"{message}|workspace={context.workspace}|cache={context.cache_root}"

    return [workspace_echo]
""".strip(),
        encoding="utf-8",
    )
    config = {
        "path": {
            "base": str(tmp_path),
            "logs": str(tmp_path),
            "sessions": str(tmp_path),
            "executor": str(tmp_path),
            "cache": str(tmp_path / "cache"),
            "skills": [],
        },
        "agent": {
            "model": {
                "model_provider": "mock",
                "model_name": "mock-model",
                "input_types": ["text"],
            },
            "builtin": {
                "tool": [],
                "skill": [],
            },
            "tools": [
                f"{factory_path}:create_tools",
            ],
        },
        "session_manager": {
            "persist": True,
        },
    }

    runner = Runner(config_type="dict", config=config)
    session_id = runner.create_session()
    agent = runner.get_agent(session_id)

    assert agent is not None
    tool_map = {tool.name: tool for tool in agent.state.tools}
    assert "workspace_echo" in tool_map

    result = asyncio.run(
        tool_map["workspace_echo"].execute(
            "test-call",
            {"message": "hello"},
        )
    )

    assert result.is_error is False
    assert result.content[0].text == (
        f"hello|workspace={tmp_path}|cache={tmp_path / 'cache'}"
    )

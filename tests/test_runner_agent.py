from __future__ import annotations

import asyncio
from pathlib import Path

from picho.runner import Runner


def _runner_config(tmp_path: Path) -> dict:
    return {
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
                "tool": ["read", "write", "bash", "edit"],
                "skill": [],
            },
            "tools": [
                "tools/custom_tools.py:create_tools",
                "sample_package.tools:create_tools",
            ],
        },
        "session_manager": {
            "persist": True,
        },
    }


def test_runner_agent_executes_custom_tool_factory_end_to_end(
    tmp_path: Path, monkeypatch
):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    factory_path = tools_dir / "custom_tools.py"
    factory_path.write_text(
        """
from picho.builtin import pi_tool
from picho.tool import Tool, ToolParameter, ToolResult


def create_tools(context):
    @pi_tool(name="context_echo")
    def context_echo(message: str) -> str:
        return (
            f"custom:{message}|workspace={context.workspace}|"
            f"cache={context.cache_root}|provider={context.config.agent.model.model_provider}"
        )

    async def execute_manual(tool_call_id, params, signal=None, on_update=None):
        return ToolResult(
            content=[{"type": "text", "text": f"manual:{params['value']}"}]
        )

    manual_tool = Tool.create(
        name="manual_echo",
        description="Manual custom tool created without pi_tool.",
        parameters=ToolParameter(
            type="object",
            properties={"value": {"type": "string"}},
            required=["value"],
        ),
        execute=execute_manual,
    )

    return [context_echo, manual_tool]
""".strip(),
        encoding="utf-8",
    )

    package_dir = tmp_path / "sample_package"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "tools.py").write_text(
        """
from picho.builtin import pi_tool


def create_tools(context):
    @pi_tool(name="package_marker")
    def package_marker() -> str:
        return "package-import-ok"

    return [package_marker]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = Runner(config_type="dict", config=_runner_config(tmp_path))
    session_id = runner.create_session()
    state = runner.get_session(session_id)
    assert state is not None

    tool_names = {tool.name for tool in state.agent.state.tools}
    assert {
        "read",
        "write",
        "bash",
        "edit",
        "context_echo",
        "manual_echo",
        "package_marker",
    }.issubset(tool_names)

    asyncio.run(
        runner.prompt(
            session_id,
            'mock_tool_call:{"name":"context_echo","arguments":{"message":"hello"}}',
        )
    )

    messages = state.agent.state.messages
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "toolResult",
        "assistant",
    ]
    expected_text = (
        f"custom:hello|workspace={tmp_path}|cache={tmp_path / 'cache'}|provider=mock"
    )
    assert messages[1].content[0].name == "context_echo"
    assert messages[2].tool_name == "context_echo"
    assert messages[2].content[0].text == expected_text
    assert messages[3].content[0].text == expected_text

    manual_session_id = runner.create_session()
    manual_state = runner.get_session(manual_session_id)
    assert manual_state is not None

    asyncio.run(
        runner.prompt(
            manual_session_id,
            'mock_tool_call:{"name":"manual_echo","arguments":{"value":"world"}}',
        )
    )

    messages = manual_state.agent.state.messages
    assert messages[-2].role == "toolResult"
    assert messages[-2].tool_name == "manual_echo"
    assert messages[-2].content[0].text == "manual:world"
    assert messages[-3].content[0].name == "manual_echo"
    assert messages[-1].content[0].text == "manual:world"

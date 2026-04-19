from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from picho.builtin.tool import HostExecutor, create_bash_tool


def _run_bash(tool, command: str):
    if tool.execute is None:
        raise RuntimeError("Bash tool execute function is not available")
    return asyncio.run(tool.execute("test-bash", {"command": command}))


def test_bash_tool_executes_command(tmp_path: Path):
    tool = create_bash_tool(HostExecutor(cwd=str(tmp_path)))
    result = _run_bash(tool, "printf 'hello from bash'")

    assert result.is_error is False
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert "hello from bash" in result.content[0].text


def test_bash_tool_uses_working_directory(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    marker.write_text("cwd test", encoding="utf-8")

    tool = create_bash_tool(HostExecutor(cwd=str(tmp_path)))
    result = _run_bash(tool, "ls")

    assert result.is_error is False
    assert "marker.txt" in result.content[0].text


def test_bash_tool_returns_error_result_for_failed_command(tmp_path: Path):
    tool = create_bash_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_bash(tool, "bash -lc 'echo boom >&2; exit 7'")

    assert result.is_error is True
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert "boom" in result.content[0].text
    assert "Command exited with code 7" in result.content[0].text


def test_bash_tool_preserves_cancelled_error_for_abort(tmp_path: Path):
    tool = create_bash_tool(HostExecutor(cwd=str(tmp_path)))

    async def run_and_abort():
        signal = asyncio.Event()
        # Abort must propagate as CancelledError so the agent loop can convert it
        # into an aborted tool result instead of treating it like a normal failure.
        task = asyncio.create_task(
            tool.execute("test-bash", {"command": "sleep 10"}, signal=signal)
        )
        await asyncio.sleep(0.1)
        signal.set()
        await task

    # This intentionally asserts the tool-layer control flow, not the final
    # ToolResult, because the aborted ToolResult is produced one layer above.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_abort())

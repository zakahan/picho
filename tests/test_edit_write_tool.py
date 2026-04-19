from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from picho.builtin.tool import HostExecutor, create_edit_tool, create_write_tool


def _run_tool(tool, params: dict):
    if tool.execute is None:
        raise RuntimeError("Tool execute function is not available")
    return asyncio.run(tool.execute("test-tool", params))


class AbortableHostExecutor(HostExecutor):
    async def exec(self, command: str, timeout: int | None = None, signal=None):
        if signal is not None:
            await signal.wait()
            raise asyncio.CancelledError("Operation aborted by user")
        return await super().exec(command, timeout=timeout, signal=signal)


def test_write_tool_writes_file(tmp_path: Path):
    tool = create_write_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_tool(tool, {"path": "notes.txt", "content": "hello"})

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert result.content[0].text == "Successfully wrote 5 bytes to notes.txt"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"


def test_write_tool_rejects_path_outside_workspace(tmp_path: Path):
    tool = create_write_tool(HostExecutor(cwd=str(tmp_path)))
    outside_dir = tmp_path.parent / f"{tmp_path.name}_outside"
    outside_dir.mkdir(exist_ok=True)
    outside_path = outside_dir / "notes.txt"

    result = _run_tool(tool, {"path": str(outside_path), "content": "hello"})

    assert result.is_error is True
    assert result.content[0].type == "text"
    assert "outside workspace" in result.content[0].text
    assert outside_path.exists() is False


def test_edit_tool_replaces_text(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\npicho\n", encoding="utf-8")
    tool = create_edit_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_tool(
        tool,
        {
            "path": "sample.txt",
            "oldText": "picho",
            "newText": "picho-next",
        },
    )

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert "Successfully replaced text in sample.txt" in result.content[0].text
    assert file_path.read_text(encoding="utf-8") == "hello\npicho-next\n"


def test_edit_tool_returns_error_when_old_text_is_missing(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\npicho\n", encoding="utf-8")
    tool = create_edit_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_tool(
        tool,
        {
            "path": "sample.txt",
            "oldText": "missing-text",
            "newText": "picho-next",
        },
    )

    assert result.is_error is True
    assert result.content[0].type == "text"
    assert "Could not find the exact text in sample.txt" in result.content[0].text
    assert file_path.read_text(encoding="utf-8") == "hello\npicho\n"


def test_edit_tool_rejects_path_outside_workspace(tmp_path: Path):
    tool = create_edit_tool(HostExecutor(cwd=str(tmp_path)))
    outside_dir = tmp_path.parent / f"{tmp_path.name}_outside"
    outside_dir.mkdir(exist_ok=True)
    outside_path = outside_dir / "sample.txt"
    outside_path.write_text("hello", encoding="utf-8")

    result = _run_tool(
        tool,
        {
            "path": str(outside_path),
            "oldText": "hello",
            "newText": "world",
        },
    )

    assert result.is_error is True
    assert result.content[0].type == "text"
    assert "outside workspace" in result.content[0].text
    assert outside_path.read_text(encoding="utf-8") == "hello"


def test_write_tool_preserves_cancelled_error_for_abort(tmp_path: Path):
    tool = create_write_tool(AbortableHostExecutor(cwd=str(tmp_path)))

    async def run_and_abort():
        signal = asyncio.Event()
        task = asyncio.create_task(
            tool.execute(
                "test-tool",
                {"path": "notes.txt", "content": "hello"},
                signal=signal,
            )
        )
        await asyncio.sleep(0.1)
        signal.set()
        await task

    # Write should preserve CancelledError so the agent loop can emit the
    # standard aborted tool result instead of a normal failure.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_abort())


def test_edit_tool_preserves_cancelled_error_for_abort(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\npicho\n", encoding="utf-8")
    tool = create_edit_tool(AbortableHostExecutor(cwd=str(tmp_path)))

    async def run_and_abort():
        signal = asyncio.Event()
        task = asyncio.create_task(
            tool.execute(
                "test-tool",
                {
                    "path": "sample.txt",
                    "oldText": "picho",
                    "newText": "picho-next",
                },
                signal=signal,
            )
        )
        await asyncio.sleep(0.1)
        signal.set()
        await task

    # Edit follows the same tool-layer abort contract as bash and write.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_abort())

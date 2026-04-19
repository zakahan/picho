from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from picho.config import ReadToolConfig
from picho.builtin.tool import HostExecutor, create_read_tool
from picho.builtin.tool.extension import read as read_extension_module
from picho.builtin.tool.extension.read import convert as read_convert_module


def _run_read(tool, path: str, **params):
    if tool.execute is None:
        raise RuntimeError("Read tool execute function is not available")
    return asyncio.run(tool.execute("test-read", {"path": path, **params}))


class AbortableHostExecutor(HostExecutor):
    async def exec(self, command: str, timeout: int | None = None, signal=None):
        if signal is not None:
            await signal.wait()
            raise asyncio.CancelledError("Operation aborted by user")
        return await super().exec(command, timeout=timeout, signal=signal)


def test_read_tool_reads_text_file(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\npicho", encoding="utf-8")

    tool = create_read_tool(HostExecutor(cwd=str(tmp_path)))
    result = _run_read(tool, str(file_path))

    assert result.is_error is False
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert "hello\npicho" in result.content[0].text


def test_read_tool_uses_custom_extension_for_csv(tmp_path: Path):
    extension_path = tmp_path / "csv_reader.py"
    extension_path.write_text(
        """
from pathlib import Path

from picho.builtin.tool.extension.read import ReadExtension, ReadExtensionContext
from picho.provider.types import TextContent
from picho.tool import ToolResult


def read_csv(context: ReadExtensionContext) -> ToolResult:
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text="[csv extension]\\n" + Path(context.resolved_path).read_text(encoding="utf-8"),
            )
        ]
    )


READ_EXTENSIONS = [
    ReadExtension(
        name="csv-reader",
        extensions=[".csv"],
        execute=read_csv,
    )
]
""".strip(),
        encoding="utf-8",
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("name,role\nalice,engineer\n", encoding="utf-8")

    tool = create_read_tool(
        HostExecutor(cwd=str(tmp_path)),
        read_config=ReadToolConfig(extensions=[str(extension_path)]),
    )
    result = _run_read(tool, "sample.csv")

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert result.content[0].text.startswith("[csv extension]\n")
    assert "name,role" in result.content[0].text


def test_read_tool_custom_extension_overrides_builtin_pdf_reader(
    tmp_path: Path, monkeypatch
):
    extension_path = tmp_path / "pdf_reader.py"
    extension_path.write_text(
        """
from picho.builtin.tool.extension.read import ReadExtension, ReadExtensionContext
from picho.provider.types import TextContent
from picho.tool import ToolResult


def read_pdf(context: ReadExtensionContext) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text="[custom pdf reader]")]
    )


READ_EXTENSIONS = [
    ReadExtension(
        name="pdf-reader",
        extensions=[".pdf"],
        execute=read_pdf,
    )
]
""".strip(),
        encoding="utf-8",
    )
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    async def fail_if_builtin_runs(*_args, **_kwargs):
        raise AssertionError(
            "builtin PDF conversion should not run when a custom extension matches"
        )

    monkeypatch.setattr(
        read_extension_module, "convert_to_markdown_async", fail_if_builtin_runs
    )

    tool = create_read_tool(
        HostExecutor(cwd=str(tmp_path)),
        read_config=ReadToolConfig(extensions=[str(extension_path)]),
    )
    result = _run_read(tool, "sample.pdf")

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert result.content[0].text == "[custom pdf reader]"


def test_read_tool_returns_error_for_missing_file(tmp_path: Path):
    tool = create_read_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_read(tool, "missing.txt")

    assert result.is_error is True
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "File not found: missing.txt"


def test_read_tool_returns_empty_file_message(tmp_path: Path):
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")
    tool = create_read_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_read(tool, "empty.txt")

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert result.content[0].text == "[File is empty: empty.txt]"


def test_read_tool_reports_offset_and_limit_pagination(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("line1\nline2\nline3\nline4\nline5", encoding="utf-8")
    tool = create_read_tool(HostExecutor(cwd=str(tmp_path)))

    result = _run_read(tool, "sample.txt", offset=2, limit=2)

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert "line2\nline3" in result.content[0].text
    assert "[2 more lines in file. Use offset=4 to continue]" in result.content[0].text


def test_read_tool_preserves_cancelled_error_for_abort(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\npicho", encoding="utf-8")
    tool = create_read_tool(AbortableHostExecutor(cwd=str(tmp_path)))

    async def run_and_abort():
        signal = asyncio.Event()
        task = asyncio.create_task(
            tool.execute("test-read", {"path": "sample.txt"}, signal=signal)
        )
        await asyncio.sleep(0.1)
        signal.set()
        await task

    # Read should preserve CancelledError so the agent loop can convert it into
    # the standard aborted tool result one layer above.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_abort())


def test_convert_to_markdown_async_preserves_cancelled_error(
    tmp_path: Path, monkeypatch
):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def slow_convert(_file_path: str, _workspace: str) -> str:
        time.sleep(0.2)
        return "converted"

    monkeypatch.setattr(read_convert_module, "convert_to_markdown", slow_convert)

    async def run_and_abort():
        signal = asyncio.Event()
        task = asyncio.create_task(
            read_convert_module.convert_to_markdown_async(
                str(pdf_path),
                str(tmp_path),
                signal=signal,
            )
        )
        await asyncio.sleep(0.05)
        signal.set()
        await task

    # The conversion still runs in a worker thread, but the await path should
    # stop immediately so agent abort stays responsive for large PDF/DOCX files.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_abort())

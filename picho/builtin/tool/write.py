"""
Write tool implementation with security checks
"""

from pathlib import Path
from typing import Any

from picho.tool import Tool, ToolResult, ToolParameter
from picho.provider.types import TextContent
from picho.tool.executor import Executor
from picho.builtin.security import validate_path
from ...logger import get_logger

_log = get_logger(__name__)


def shell_escape(s: str) -> str:
    """Escape string for shell"""
    return "'" + s.replace("'", "'\\''") + "'"


def _build_error_result(message: str) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )


def create_write_tool(executor: Executor) -> Tool:
    """
    Create a write tool for writing content to files.

    Creates the file if it doesn't exist, overwrites if it does.
    Automatically creates parent directories.
    Only files within the workspace can be written.
    """

    async def execute_write(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")

        _log.debug(
            f"Execute write start tool_call_id={tool_call_id} path={path} content_len={len(content)}"
        )

        if not path:
            _log.error("Execute write failed: path is required")
            return _build_error_result("Path is required")

        _log.debug(f"Validating path: {path}")
        path_result = validate_path(path, executor.cwd)
        if not path_result.allowed:
            _log.error(f"Path validation failed: {path_result.reason}")
            return _build_error_result(path_result.reason)

        workspace_path = executor.get_workspace_path(path)
        _log.debug(f"Workspace path: {workspace_path}")

        dir_path = str(Path(workspace_path).parent)
        if dir_path and dir_path != ".":
            _log.debug(f"Creating directory: {dir_path}")
            mkdir_result = await executor.exec(
                f"mkdir -p {shell_escape(dir_path)}", signal=signal
            )
            if mkdir_result.code != 0:
                _log.error(f"Failed to create directory: {mkdir_result.stderr}")
                return _build_error_result(
                    mkdir_result.stderr or f"Failed to create directory: {dir_path}"
                )

        _log.debug(f"Writing file content: {workspace_path}")
        cmd = f"printf '%s' {shell_escape(content)} > {shell_escape(workspace_path)}"
        result = await executor.exec(cmd, signal=signal)

        if result.code != 0:
            _log.error(f"Failed to write file: {result.stderr}")
            return _build_error_result(result.stderr or f"Failed to write file: {path}")

        _log.debug(
            f"Execute write success tool_call_id={tool_call_id} wrote={len(content)} bytes"
        )
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Successfully wrote {len(content)} bytes to {path}",
                )
            ],
        )

    return Tool.create(
        name="write",
        description="""Write content to a file.

Behavior:
- Creates the file if it doesn't exist
- Overwrites the file if it exists (complete replacement)
- Automatically creates parent directories

Output format:
- Success: "Successfully wrote N bytes to <path>"
- Error: "Failed to write file: <path>" (permission denied, disk full, etc.)

WARNING: This completely replaces file content. Use 'edit' for partial changes.

Only files within the workspace can be written.""",
        parameters=ToolParameter(
            type="object",
            properties={
                "path": {
                    "type": "string",
                    "description": "Path to the file to write (relative or absolute, must be within workspace)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            required=["path", "content"],
        ),
        execute=execute_write,
    )

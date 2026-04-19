"""
Bash tool implementation with security checks
"""

import asyncio
import os
import tempfile
import secrets
import traceback
from typing import Any

from picho.tool import Tool, ToolResult, ToolParameter
from picho.provider.types import TextContent
from picho.tool.truncate import (
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_BYTES,
    format_size,
    truncate_tail,
)
from picho.tool.executor import Executor
from ...logger import get_logger

_log = get_logger(__name__)


def _get_temp_file_path() -> str:
    """Generate a unique temp file path for bash output"""
    temp_dir = tempfile.gettempdir()
    file_id = secrets.token_hex(8)
    return os.path.join(temp_dir, f"picho-bash-{file_id}.log")


def _load_env_file(env_path: str) -> dict[str, str]:
    """Load environment variables from a .env file"""
    env_vars = {}
    if not os.path.exists(env_path):
        _log.warning(f"Env file not found: {env_path}")
        return env_vars

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                env_vars[key] = value
    _log.debug(f"Loaded {len(env_vars)} env vars from {env_path}")
    return env_vars


def _build_error_result(message: str) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )


def create_bash_tool(
    executor: Executor, env_path: str | None = None, init_command: str | None = None
) -> Tool:
    """
    Create a bash tool for executing bash commands.

    Executes a bash command in the executor's working directory.
    Returns stdout and stderr.
    Output is truncated to last DEFAULT_MAX_LINES lines or DEFAULT_MAX_BYTES bytes.

    Args:
        executor: The executor to use for command execution
        env_path: Optional path to a .env file to load environment variables from
        init_command: Optional command to execute before each user command (e.g., "export PATH=/my/python:$PATH")
    """
    if env_path:
        env_vars = _load_env_file(env_path)
        if env_vars and hasattr(executor, "_env") and executor.env is None:
            executor._env = env_vars
            _log.info(f"Loaded {len(env_vars)} env vars from {env_path}")

    async def execute_bash(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        raw_command = params.get("command", "")
        command = raw_command
        timeout = params.get("timeout")
        label = params.get("label", "")

        if init_command:
            command = f"{init_command}; {command}"

        _log.debug(
            f"Execute bash start tool_call_id={tool_call_id} label={label} timeout={timeout}"
        )
        _log.debug(f"Bash command: {command}")

        if not command:
            _log.error("Execute bash failed: command is required")
            return _build_error_result("Command is required")

        try:
            _log.debug("Executing command via executor")
            result = await executor.exec(command, timeout=timeout, signal=signal)
            _log.debug(
                f"Executor returned: code={result.code} stdout_len={len(result.stdout)} stderr_len={len(result.stderr)}"
            )

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n"
                output += result.stderr

            if not output:
                output = "(no output)"

            total_bytes = len(output.encode("utf-8"))
            temp_file_path = None

            _log.debug(f"Bash output total_bytes={total_bytes}")

            if total_bytes > DEFAULT_MAX_BYTES:
                temp_file_path = _get_temp_file_path()
                _log.debug(
                    f"Output exceeds limit, saving to temp file: {temp_file_path}"
                )
                with open(temp_file_path, "w", encoding="utf-8") as f:
                    f.write(output)

            truncation = truncate_tail(output)
            output_text = truncation.content

            if truncation.truncated:
                start_line = truncation.total_lines - truncation.output_lines + 1
                end_line = truncation.total_lines

                _log.debug(
                    f"Output truncated: truncated_by={truncation.truncated_by} total_lines={truncation.total_lines} output_lines={truncation.output_lines}"
                )

                if truncation.last_line_partial:
                    last_line_size = format_size(
                        len(output.split("\n")[-1].encode("utf-8"))
                    )
                    output_text += f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end_line} (line is {last_line_size}). Full output: {temp_file_path}]"
                elif truncation.truncated_by == "lines":
                    output_text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. Full output: {temp_file_path}]"
                else:
                    output_text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {temp_file_path}]"

            if result.code != 0:
                if result.code == 1 and not result.stdout and not result.stderr:
                    _log.info(
                        "Bash command exited with code 1 and no output; returning informational result"
                    )
                    return ToolResult(
                        content=[
                            TextContent(
                                type="text",
                                text=(
                                    f"[Command returned no output: {raw_command}]\n"
                                    "Exit code: 1\n"
                                    "For commands like grep, this usually means no matches were found."
                                ),
                            )
                        ],
                    )
                _log.error(f"Bash command failed with exit code {result.code}")
                return _build_error_result(
                    f"{output_text}\n\nCommand exited with code {result.code}"
                )

            _log.debug(f"Execute bash success tool_call_id={tool_call_id}")
            return ToolResult(
                content=[TextContent(type="text", text=output_text)],
            )

        except asyncio.CancelledError:
            _log.info("Execute bash aborted by user")
            raise
        except Exception as e:
            error_traceback = traceback.format_exc()
            _log.error(f"Execute bash error: {e}\n{error_traceback}")
            if isinstance(e, TimeoutError):
                return _build_error_result(str(e))
            return _build_error_result(f"Failed to execute command: {str(e)}")

    return Tool.create(
        name="bash",
        description=f"""Execute a bash command in the current working directory. Returns stdout and stderr.

SECURITY NOTICE:
Some commands are considered dangerous and will be intercepted by the security system.
Dangerous commands include: rm, chmod, chown, dd, mkfs, fdisk, shutdown, reboot, curl|bash, etc.
If a command is intercepted, the user will be asked to confirm before execution.
If the user rejects, the command will NOT be executed - do NOT retry the same command.

Output handling:
- Output is truncated to last {DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES / 1024:.0f}KB (whichever is hit first)
- If truncated, full output is saved to a temp file (path shown in output)
- Empty output: "(no output)"

Output format:
- Success: stdout/stderr content + "[Showing lines X-Y of N. Full output: /tmp/path]" if truncated
- Error: output + "Command exited with code N"

Optionally provide a timeout in seconds.""",
        parameters=ToolParameter(
            type="object",
            properties={
                "command": {
                    "type": "string",
                    "description": "Bash command to execute",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (optional, no default timeout)",
                },
                "label": {
                    "type": "string",
                    "description": "Brief description of what this command does (shown to user)",
                },
            },
            required=["command"],
        ),
        execute=execute_bash,
    )

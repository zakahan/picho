"""
Edit tool implementation with security checks
"""

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


def generate_diff(old_content: str, new_content: str, context_lines: int = 4) -> str:
    """Generate a unified diff string with line numbers and context"""
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")
    max_line_num = max(len(old_lines), len(new_lines))
    line_num_width = len(str(max_line_num))

    output = []
    old_line_num = 1
    new_line_num = 1
    i = 0

    while i < len(old_lines) or i < len(new_lines):
        if i < len(old_lines) and i < len(new_lines) and old_lines[i] == new_lines[i]:
            old_num = str(old_line_num).rjust(line_num_width)
            output.append(f" {old_num} {old_lines[i]}")
            old_line_num += 1
            new_line_num += 1
            i += 1
        else:
            start_context = []
            if i > 0:
                start_idx = max(0, i - context_lines)
                for j in range(start_idx, i):
                    old_num = str(j + 1).rjust(line_num_width)
                    if old_lines[j] == new_lines[j] if j < len(new_lines) else False:
                        start_context.append(f" {old_num} {old_lines[j]}")

            if start_context and len(start_context) > context_lines:
                output.append(" " + " " * line_num_width + " ...")
                start_context = start_context[-context_lines:]
            output.extend(start_context)

            new_start = i

            while i < len(old_lines) and (
                i >= len(new_lines) or old_lines[i] != new_lines[i]
            ):
                if i < len(new_lines) and old_lines[i] != new_lines[i]:
                    old_num = str(old_line_num).rjust(line_num_width)
                    output.append(f"-{old_num} {old_lines[i]}")
                    old_line_num += 1
                    i += 1
                elif i >= len(new_lines):
                    old_num = str(old_line_num).rjust(line_num_width)
                    output.append(f"-{old_num} {old_lines[i]}")
                    old_line_num += 1
                    i += 1
                else:
                    break

            while new_start < len(new_lines) and (
                new_start >= len(old_lines)
                or old_lines[new_start] != new_lines[new_start]
            ):
                if (
                    new_start >= len(old_lines)
                    or old_lines[new_start] != new_lines[new_start]
                ):
                    new_num = str(new_line_num).rjust(line_num_width)
                    output.append(f"+{new_num} {new_lines[new_start]}")
                    new_line_num += 1
                    new_start += 1
                else:
                    break

            if new_start > i:
                i = new_start

            end_context = []
            end_idx = min(i + context_lines, len(old_lines), len(new_lines))
            for j in range(i, end_idx):
                if (
                    j < len(old_lines)
                    and j < len(new_lines)
                    and old_lines[j] == new_lines[j]
                ):
                    old_num = str(j + 1).rjust(line_num_width)
                    end_context.append(f" {old_num} {old_lines[j]}")

            if end_context:
                if len(end_context) > context_lines:
                    end_context = end_context[:context_lines]
                    output.extend(end_context)
                    output.append(" " + " " * line_num_width + " ...")
                else:
                    output.extend(end_context)

    return "\n".join(output)


def create_edit_tool(executor: Executor) -> Tool:
    """
    Create an edit tool for editing files by replacing text.

    The oldText must match exactly (including whitespace).
    Use this for precise, surgical edits.
    Only files within the workspace can be edited.
    """

    async def execute_edit(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        path = params.get("path", "")
        old_text = params.get("oldText", "")
        new_text = params.get("newText", "")

        _log.debug(
            f"Execute edit start tool_call_id={tool_call_id} path={path} old_text_len={len(old_text)} new_text_len={len(new_text)}"
        )

        if not path:
            _log.error("Execute edit failed: path is required")
            return _build_error_result("Path is required")
        if not old_text:
            _log.error("Execute edit failed: oldText is required")
            return _build_error_result("oldText is required")

        _log.debug(f"Validating path: {path}")
        path_result = validate_path(path, executor.cwd)
        if not path_result.allowed:
            _log.error(f"Path validation failed: {path_result.reason}")
            return _build_error_result(path_result.reason)

        workspace_path = executor.get_workspace_path(path)
        _log.debug(f"Workspace path: {workspace_path}")

        _log.debug(f"Reading file content: {workspace_path}")
        read_result = await executor.exec(
            f"cat {shell_escape(workspace_path)}", signal=signal
        )
        if read_result.code != 0:
            _log.error(f"Failed to read file: {read_result.stderr}")
            return _build_error_result(read_result.stderr or f"File not found: {path}")

        content = read_result.stdout
        _log.debug(f"Read file content length: {len(content)}")

        if old_text not in content:
            _log.error(f"Old text not found in file: {path}")
            return _build_error_result(
                f"Could not find the exact text in {path}. The old text must match exactly including all whitespace and newlines."
            )

        occurrences = content.count(old_text)
        _log.debug(f"Found {occurrences} occurrences of old text")

        if occurrences > 1:
            _log.error(f"Multiple occurrences found: {occurrences}")
            return _build_error_result(
                f"Found {occurrences} occurrences of the text in {path}. The text must be unique. Please provide more context to make it unique."
            )

        _log.debug(f"Replacing text: {len(old_text)} chars -> {len(new_text)} chars")
        new_content = content.replace(old_text, new_text, 1)

        if content == new_content:
            _log.error("No changes made, old_text equals new_text")
            return _build_error_result(
                f"No changes made to {path}. The replacement produced identical content. This might indicate an issue with special characters or the text not existing as expected."
            )

        _log.debug(f"Writing updated content to file: {workspace_path}")
        write_result = await executor.exec(
            f"printf '%s' {shell_escape(new_content)} > {shell_escape(workspace_path)}",
            signal=signal,
        )

        if write_result.code != 0:
            _log.error(f"Failed to write file: {write_result.stderr}")
            return _build_error_result(
                write_result.stderr or f"Failed to write file: {path}"
            )

        _log.debug("Generating diff")
        diff = generate_diff(content, new_content)

        _log.debug(f"Execute edit success tool_call_id={tool_call_id}")
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Successfully replaced text in {path}. Changed {len(old_text)} characters to {len(new_text)} characters.\n\nDiff:\n{diff}",
                )
            ],
        )

    return Tool.create(
        name="edit",
        description="""Edit a file by replacing exact text. The oldText must match exactly (including whitespace).

Behavior:
- oldText must exist exactly once in the file (unique match required)
- If multiple matches found, provide more context to make it unique
- Creates no changes if oldText equals newText

Output format:
- Success: "Successfully replaced text in <path>. Changed X characters to Y characters." + diff
- Error: "Could not find the exact text" or "Found N occurrences" (must be unique)

The diff shows:
- Lines prefixed with "-" are removed (old content)
- Lines prefixed with "+" are added (new content)
- Context lines show surrounding unchanged content

Only files within the workspace can be edited.""",
        parameters=ToolParameter(
            type="object",
            properties={
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit (relative or absolute, must be within workspace)",
                },
                "oldText": {
                    "type": "string",
                    "description": "Exact text to find and replace (must match exactly)",
                },
                "newText": {
                    "type": "string",
                    "description": "New text to replace the old text with",
                },
            },
            required=["path", "oldText", "newText"],
        ),
        execute=execute_edit,
    )

"""
Truncation utilities for tool outputs
"""

from dataclasses import dataclass

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50000


@dataclass
class TruncationResult:
    content: str
    truncated: bool = False
    truncated_by: str = ""  # "lines" or "bytes"
    total_lines: int = 0
    total_bytes: int = 0
    output_lines: int = 0
    output_bytes: int = 0
    first_line_exceeds_limit: bool = False
    last_line_partial: bool = False


def format_size(bytes_count: int) -> str:
    """Format byte count as human readable string"""
    if bytes_count < 1024:
        return f"{bytes_count}B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f}KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f}MB"


def truncate_head(
    content: str, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> TruncationResult:
    """
    Truncate content from the head (beginning).
    Returns the first max_lines or max_bytes of content.
    Suitable for file reads where you want to see the beginning.
    """
    if not content:
        return TruncationResult(content="", truncated=False)

    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = len(content.encode("utf-8"))

    if total_bytes <= max_bytes and total_lines <= max_lines:
        return TruncationResult(
            content=content,
            truncated=False,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
        )

    first_line_bytes = len(lines[0].encode("utf-8"))
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            first_line_exceeds_limit=True,
        )

    output_lines_list = []
    output_bytes = 0
    truncated_by = "lines"

    for line in lines:
        line_bytes = len(line.encode("utf-8")) + (1 if output_lines_list else 0)

        if output_bytes + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        if len(output_lines_list) >= max_lines:
            truncated_by = "lines"
            break

        output_lines_list.append(line)
        output_bytes += line_bytes

    output_content = "\n".join(output_lines_list)

    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_list),
        output_bytes=len(output_content.encode("utf-8")),
    )


def truncate_tail(
    content: str, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> TruncationResult:
    """
    Truncate content from the tail (end).
    Returns the last max_lines or max_bytes of content.
    Suitable for bash output where you want to see the end (errors, final results).
    May return partial first line if the last line exceeds byte limit.
    """
    if not content:
        return TruncationResult(content="", truncated=False)

    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = len(content.encode("utf-8"))

    if total_bytes <= max_bytes and total_lines <= max_lines:
        return TruncationResult(
            content=content,
            truncated=False,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
        )

    output_lines_list = []
    output_bytes = 0
    truncated_by = "lines"
    last_line_partial = False

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        line_bytes = len(line.encode("utf-8")) + (1 if output_lines_list else 0)

        if output_bytes + line_bytes > max_bytes:
            truncated_by = "bytes"
            if not output_lines_list:
                truncated_line = _truncate_string_from_end(line, max_bytes)
                output_lines_list.insert(0, truncated_line)
                output_bytes = len(truncated_line.encode("utf-8"))
                last_line_partial = True
            break
        if len(output_lines_list) >= max_lines:
            truncated_by = "lines"
            break

        output_lines_list.insert(0, line)
        output_bytes += line_bytes

    output_content = "\n".join(output_lines_list)

    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_list),
        output_bytes=len(output_content.encode("utf-8")),
        last_line_partial=last_line_partial,
    )


def _truncate_string_from_end(s: str, max_bytes: int) -> str:
    """Truncate a string to fit within a byte limit (from the end)."""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s

    start = len(encoded) - max_bytes

    while start < len(encoded) and (encoded[start] & 0xC0) == 0x80:
        start += 1

    return encoded[start:].decode("utf-8")

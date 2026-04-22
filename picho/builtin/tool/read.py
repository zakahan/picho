"""
Read tool implementation
"""

import os
from pathlib import Path
from typing import Any

from picho.config import ReadToolConfig
from picho.tool import Tool, ToolResult, ToolParameter
from picho.provider.types import TextContent, ImageBase64Content, VideoFileIdContent
from picho.tool.truncate import (
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_BYTES,
    format_size,
    truncate_head,
)
from picho.tool.executor import Executor
from ...logger import get_logger
from .extension.read import (
    ReadExtensionContext,
    execute_read_extension,
    find_read_extension,
    load_read_extensions,
)
from .extension.read.parser import SUPPORTED_DOCUMENT_EXTENSIONS

_log = get_logger(__name__)

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


def shell_escape(s: str) -> str:
    """Escape string for shell"""
    return "'" + s.replace("'", "'\\''") + "'"


def is_image_file(file_path: str) -> str | None:
    """Check if file is an image based on extension"""
    ext = Path(file_path).suffix.lower()
    return IMAGE_MIME_TYPES.get(ext)


def is_video_file(file_path: str) -> str | None:
    """Check if file is a video based on extension"""
    ext = Path(file_path).suffix.lower()
    return VIDEO_MIME_TYPES.get(ext)


def judge_file_type(file_path: str) -> str:
    """
    Determine file type based on file path.

    :param file_path: Full path of the file
    :return: "extra" (pdf/docx), "image", "video", "not_supported", "not_exist", or "text"
    """
    path = Path(file_path)

    if not path.exists():
        return "not_exist"

    file_ext = path.suffix.lower()

    binary_extensions = {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".zip",
        ".tar",
        ".gz",
        ".rar",
        ".7z",
        ".iso",
    }

    if file_ext in SUPPORTED_DOCUMENT_EXTENSIONS:
        return "extra"
    elif file_ext in IMAGE_MIME_TYPES:
        return "image"
    elif file_ext in VIDEO_MIME_TYPES:
        return "video"
    elif file_ext in binary_extensions:
        return "not_supported"
    else:
        return "text"


def _format_file_size(size_bytes: int) -> str:
    return f"{size_bytes / 1024 / 1024:.1f}MB"


def _build_error_result(message: str) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )


def _build_video_compression_unavailable_message(
    limit_bytes: int, error: Exception
) -> str:
    limit_text = _format_file_size(limit_bytes)
    return (
        f"Read video file preparation requires automatic compression because the source video exceeds the configured limit of {limit_text}, "
        f"but compression is unavailable: {error}.\n"
        "This result is informational only. Do not modify user configuration automatically.\n"
        "Ask the user to choose one of these options:\n"
        "1. Install ffmpeg/ffprobe, or compress/split the video manually, if the current model/provider really enforces this file size limit.\n"
        "2. Raise `tool_config.read.video_compression.trigger_size_mb` or disable `tool_config.read.video_compression.enabled` only if the user confirms this limit does not apply to the current model/provider.\n"
        "picho is falling back to the original video for this read attempt."
    )


def _build_video_limit_exceeded_with_compression_disabled_message(
    file_size_bytes: int,
    limit_bytes: int,
) -> str:
    return (
        f"This video exceeds the configured size limit for direct reading: {_format_file_size(file_size_bytes)} > {_format_file_size(limit_bytes)}.\n"
        "Automatic video compression is currently disabled via `tool_config.read.video_compression.enabled=false`.\n"
        "This result is informational only. Do not modify user configuration automatically.\n"
        "Ask the user to choose one of these options:\n"
        "1. Enable automatic compression.\n"
        "2. Raise `tool_config.read.video_compression.trigger_size_mb` only if the user confirms this limit does not apply to the current model/provider.\n"
        "3. Compress or split the video manually before reading."
    )


def _resolve_read_path(path: str, workspace: str) -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return str(Path(expanded).resolve())
    return str((Path(workspace) / expanded).resolve())


def create_read_tool(
    executor: Executor,
    read_config: ReadToolConfig | None = None,
    cache_root: str | None = None,
) -> Tool:
    """
    Create a read tool for reading file contents.
    """
    cache_base = cache_root or executor.cwd
    custom_read_extensions = load_read_extensions(
        read_config.extensions if read_config else [],
        executor.cwd,
    )

    async def execute_read(
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        path = params.get("path", "")
        offset = params.get("offset")
        limit = params.get("limit")

        _log.debug(
            f"Execute read start tool_call_id={tool_call_id} path={path} offset={offset} limit={limit}"
        )

        if not path:
            _log.error("Execute read failed: path is required")
            return _build_error_result("Path is required")

        resolved_path = _resolve_read_path(path, executor.cwd)
        _log.debug(f"Resolved read path: requested={path} resolved={resolved_path}")

        file_type = judge_file_type(resolved_path)
        _log.debug(f"File type determined: {file_type} path={resolved_path}")

        if file_type == "not_exist":
            _log.error(f"File not found: {path}")
            return _build_error_result(f"File not found: {path}")

        custom_extension = find_read_extension(resolved_path, custom_read_extensions)
        if custom_extension is not None:
            _log.debug(
                f"Processing file with custom read extension: {custom_extension.name} path={resolved_path}"
            )
            return await execute_read_extension(
                custom_extension,
                ReadExtensionContext(
                    tool_call_id=tool_call_id,
                    params=params,
                    requested_path=path,
                    resolved_path=resolved_path,
                    offset=offset,
                    limit=limit,
                    executor=executor,
                    cache_root=cache_base,
                    signal=signal,
                ),
            )

        if file_type == "not_supported":
            _log.warning(f"File type not supported: {path}")
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="The file type you are attempting to read is not supported by this tool.",
                    ),
                ],
            )

        if file_type == "extra":
            _log.debug(f"Processing extra file type (PDF/DOCX): {path}")
            import traceback

            try:
                from picho.builtin.tool.extension.read import (
                    convert_to_markdown_async,
                    get_cache_dir,
                )
            except ImportError as e:
                _log.error(f"Extra dependencies not installed: {e}")
                return ToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="PDF/DOCX support requires optional dependency group `super-reader`. "
                            'Install with: uv add picho["super-reader"] '
                            "or pip install 'picho[super-reader]'"
                            f"\n\nError: {e}",
                        ),
                    ],
                )

            try:
                _log.debug(f"Converting file to markdown: {resolved_path}")
                md_content = await convert_to_markdown_async(
                    resolved_path,
                    cache_base,
                    signal=signal,
                )
            except Exception as e:
                error_traceback = traceback.format_exc()
                _log.error(f"File conversion failed: {e}\n{error_traceback}")
                return ToolResult(
                    content=[
                        TextContent(type="text", text=f"Failed to convert file: {e}"),
                    ],
                    is_error=True,
                )
            cache_dir = get_cache_dir(resolved_path, cache_base)
            lines = md_content.split("\n")
            total_file_lines = len(lines)
            _log.debug(f"Converted markdown lines: {total_file_lines}")

            start_line = 1
            if offset is not None:
                start_line = max(1, offset)

            if start_line > total_file_lines:
                _log.error(
                    f"Offset {offset} beyond end of content ({total_file_lines} lines)"
                )
                return _build_error_result(
                    f"Offset {offset} is beyond end of converted content ({total_file_lines} lines total)"
                )

            end_line = total_file_lines
            if limit is not None:
                end_line = min(start_line + limit - 1, total_file_lines)

            selected_lines = lines[start_line - 1 : end_line]
            selected_content = "\n".join(selected_lines)
            _log.debug(f"Selected lines: {start_line}-{end_line}")

            truncation = truncate_head(selected_content)

            if truncation.first_line_exceeds_limit:
                first_line_size = format_size(len(selected_lines[0].encode("utf-8")))
                _log.warning(f"First line exceeds limit: {first_line_size}")
                output_text = f"[Line {start_line} is {first_line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit.]"
                return ToolResult(
                    content=[TextContent(type="text", text=output_text)],
                )

            output_text = truncation.content
            actual_end_line = start_line + truncation.output_lines - 1

            ext = Path(path).suffix.lower()
            relative_cache_dir = (
                cache_dir.relative_to(cache_base)
                if cache_dir.is_absolute()
                else cache_dir
            )
            output_text += f"\n\n[Converted from {ext}. Cache: {relative_cache_dir}]"
            output_text += f"\n[Showing lines {start_line}-{actual_end_line} of {total_file_lines} (converted markdown)]"

            if actual_end_line < total_file_lines:
                next_offset = actual_end_line + 1
                output_text += f". Use offset={next_offset} to continue"

            _log.debug(f"Execute read success (extra file) tool_call_id={tool_call_id}")
            return ToolResult(
                content=[TextContent(type="text", text=output_text)],
            )

        if file_type == "image":
            _log.debug(f"Processing image file: {path}")
            image_mime_type = is_image_file(resolved_path)
            _log.debug(f"Image MIME type: {image_mime_type}")
            result = await executor.exec(
                f"base64 < {shell_escape(resolved_path)}", signal=signal
            )
            if result.code != 0:
                _log.error(f"Failed to read image file: {result.stderr}")
                return _build_error_result(
                    result.stderr or f"Failed to read file: {path}"
                )

            import re

            base64_data = re.sub(r"\s", "", result.stdout)
            _log.debug(f"Image base64 data length: {len(base64_data)}")

            _log.debug(f"Execute read success (image) tool_call_id={tool_call_id}")
            return ToolResult(
                content=[
                    TextContent(
                        type="text", text=f"Read image file [{image_mime_type}]"
                    ),
                    ImageBase64Content(
                        type="image_base64", data=base64_data, mime_type=image_mime_type
                    ),
                ],
            )

        if file_type == "video":
            _log.debug(f"Processing video file: {path}")
            video_mime_type = is_video_file(resolved_path)
            video_path = str(Path(resolved_path).resolve())
            video_note = f"Read video file [{video_mime_type}]"
            file_size_bytes = Path(video_path).stat().st_size
            limit_bytes = (
                read_config.video_compression.trigger_size_bytes
                if read_config
                else 512 * 1024 * 1024
            )

            if file_size_bytes > limit_bytes:
                _log.info(
                    "Oversized video detected for read: "
                    f"path={video_path} "
                    f"size={_format_file_size(file_size_bytes)} "
                    f"limit={_format_file_size(limit_bytes)}"
                )
                if not (read_config and read_config.video_compression.enabled):
                    return ToolResult(
                        content=[
                            TextContent(
                                type="text",
                                text=_build_video_limit_exceeded_with_compression_disabled_message(
                                    file_size_bytes=file_size_bytes,
                                    limit_bytes=limit_bytes,
                                ),
                            )
                        ],
                        is_error=True,
                    )
                try:
                    from picho.builtin.tool.extension.read import (
                        VideoCompressionFailedError,
                        VideoCompressionUnavailableError,
                        prepare_video_for_read,
                    )

                    prepared_video = await prepare_video_for_read(
                        file_path=video_path,
                        workspace=cache_base,
                        executor=executor,
                        limit_bytes=limit_bytes,
                        signal=signal,
                    )
                    video_path = prepared_video.output_path
                    if prepared_video.was_compressed:
                        cache_state = (
                            "cache hit"
                            if prepared_video.used_cache
                            else "fresh compression"
                        )
                        relative_cache_dir = (
                            prepared_video.cache_dir.relative_to(cache_base)
                            if prepared_video.cache_dir.is_absolute()
                            else prepared_video.cache_dir
                        )
                        video_note += (
                            f". Source video exceeded {_format_file_size(limit_bytes)}, "
                            f"using compressed video "
                            f"({_format_file_size(prepared_video.original_size_bytes)} -> "
                            f"{_format_file_size(prepared_video.output_size_bytes)}, {cache_state}, "
                            f"cache: {relative_cache_dir})"
                        )
                except VideoCompressionUnavailableError as e:
                    _log.warning(
                        "Video compression unavailable, falling back to original file: "
                        f"path={video_path} error={e}"
                    )
                    video_note = _build_video_compression_unavailable_message(
                        limit_bytes, e
                    )
                except VideoCompressionFailedError as e:
                    _log.error(
                        "Video compression failed before upload: "
                        f"path={video_path} error={e}"
                    )
                    user_message = (
                        e.to_user_message()
                        if hasattr(e, "to_user_message")
                        else (
                            "Failed to prepare oversized video for model input. "
                            f"Configured limit: {_format_file_size(limit_bytes)}. Error: {e}"
                        )
                    )
                    return ToolResult(
                        content=[
                            TextContent(
                                type="text",
                                text=user_message,
                            )
                        ],
                        is_error=True,
                    )

            _log.debug(f"Video MIME type: {video_mime_type} final_path={video_path}")
            _log.debug(f"Execute read success (video) tool_call_id={tool_call_id}")
            return ToolResult(
                content=[
                    TextContent(type="text", text=video_note),
                    VideoFileIdContent(
                        type="video_file_id", file_id=None, file_path=video_path
                    ),
                ]
            )

        _log.debug(f"Processing text file: {path}")
        count_result = await executor.exec(
            f"wc -l < {shell_escape(resolved_path)}", signal=signal
        )
        if count_result.code != 0:
            _log.error(f"Failed to count lines: {count_result.stderr}")
            return _build_error_result(
                count_result.stderr or f"Failed to read file: {path}"
            )

        total_file_lines = int(count_result.stdout.strip()) + 1
        _log.debug(f"Total file lines: {total_file_lines}")

        start_line = 1
        if offset is not None:
            start_line = max(1, offset)

        if start_line > total_file_lines:
            _log.error(f"Offset {offset} beyond end of file ({total_file_lines} lines)")
            return _build_error_result(
                f"Offset {offset} is beyond end of file ({total_file_lines} lines total)"
            )

        if start_line == 1:
            cmd = f"cat {shell_escape(resolved_path)}"
        else:
            cmd = f"tail -n +{start_line} {shell_escape(resolved_path)}"
        _log.debug(f"Reading file with command: {cmd}")

        result = await executor.exec(cmd, signal=signal)
        if result.code != 0:
            _log.error(f"Failed to read file: {result.stderr}")
            return _build_error_result(result.stderr or f"Failed to read file: {path}")

        selected_content = result.stdout
        _log.debug(f"Read content length: {len(selected_content)}")

        if not selected_content.strip():
            _log.debug(f"File is empty: {path}")
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"[File is empty: {path}]",
                    )
                ],
            )

        user_limited_lines = None

        if limit is not None:
            lines = selected_content.split("\n")
            selected_content = "\n".join(lines[:limit])
            user_limited_lines = len(lines[:limit])
            _log.debug(f"Applied limit: {limit} lines, kept: {user_limited_lines}")

        truncation = truncate_head(selected_content)

        if truncation.first_line_exceeds_limit:
            first_line_size = format_size(
                len(selected_content.split("\n")[0].encode("utf-8"))
            )
            _log.warning(f"First line exceeds limit: {first_line_size}")
            output_text = f"[Line {start_line} is {first_line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. Use bash: sed -n '{start_line}p' {path} | head -c {DEFAULT_MAX_BYTES}]"
            return ToolResult(
                content=[TextContent(type="text", text=output_text)],
            )

        output_text = truncation.content
        end_line = start_line + truncation.output_lines - 1
        _log.debug(
            f"Truncated output: truncated_by={truncation.truncated_by} output_lines={truncation.output_lines}"
        )

        if truncation.truncated:
            next_offset = end_line + 1

            if truncation.truncated_by == "lines":
                output_text += f"\n\n[Showing lines {start_line}-{end_line} of {total_file_lines}. Use offset={next_offset} to continue]"
            else:
                output_text += f"\n\n[Showing lines {start_line}-{end_line} of {total_file_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={next_offset} to continue]"
        elif user_limited_lines is not None:
            lines_from_start = start_line - 1 + user_limited_lines
            if lines_from_start < total_file_lines:
                remaining = total_file_lines - lines_from_start
                next_offset = start_line + user_limited_lines
                output_text += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue]"
            else:
                output_text += f"\n\n[Showing lines {start_line}-{end_line} of {total_file_lines} (complete)]"
        else:
            if start_line == 1 and end_line == total_file_lines:
                output_text += f"\n\n[Showing lines 1-{total_file_lines} of {total_file_lines} (complete file)]"
            else:
                output_text += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {total_file_lines}]"
                )

        _log.debug(f"Execute read success (text) tool_call_id={tool_call_id}")
        return ToolResult(
            content=[TextContent(type="text", text=output_text)],
        )

    return Tool.create(
        name="read",
        description=f"""Read the contents of a file. Supports text files, images (jpg, png, gif, webp), video (mp4, avi...), PDF and DOCX. Images and Videos are sent as attachments.

For text files:
- Output is truncated to {DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES / 1024:.0f}KB (whichever is hit first)
- Use offset/limit for large files

For PDF/DOCX files:
- Files are converted to markdown format
- offset/limit apply to the converted markdown lines
- Requires optional dependency group `super-reader`: uv add picho["super-reader"] or pip install 'picho[super-reader]'

For video files:
- Returns the original video by default
- If `tool_config.read.video_compression.enabled=true` and the file exceeds the configured size limit, picho will try to compress it with ffmpeg while keeping audio
- Compressed videos are cached under `.picho/cache/files`
- If `tool_config.read.extensions` is configured, matching files can be handled by user-defined read extensions

Output format:
- Complete file: "[Showing lines 1-N of N (complete file)]"
- Truncated: "[Showing lines X-Y of N. Use offset=Y+1 to continue]"
- Empty file: "[File is empty: <path>]"
- PDF/DOCX: "[Converted from .pdf. Showing lines X-Y of N (converted markdown)]"

Note: 
    The tool supports multiple types, 
    but the model may not support multimodality, so they may be filtered out.

When you see "(complete file)", the entire file has been read. When you see "Use offset=...", there is more content to read.""",
        parameters=ToolParameter(
            type="object",
            properties={
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute, must be within workspace)",
                },
                "offset": {
                    "type": "number",
                    "description": "Line number to start reading from (1-indexed)",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum number of lines to read",
                },
            },
            required=["path"],
        ),
        execute=execute_read,
    )

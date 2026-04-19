"""
Extension module for reading additional file formats and media preprocessors.
"""

from picho.builtin.tool.extension.read.convert import (
    convert_to_markdown,
    convert_to_markdown_async,
    get_cache_dir,
)
from picho.builtin.tool.extension.read.custom import (
    ReadExtension,
    ReadExtensionContext,
    execute_read_extension,
    find_read_extension,
    load_read_extensions,
)
from picho.builtin.tool.extension.read.video import (
    VideoCompressionFailedError,
    VideoCompressionUnavailableError,
    prepare_video_for_read,
)

__all__ = [
    "convert_to_markdown",
    "convert_to_markdown_async",
    "get_cache_dir",
    "ReadExtension",
    "ReadExtensionContext",
    "load_read_extensions",
    "find_read_extension",
    "execute_read_extension",
    "prepare_video_for_read",
    "VideoCompressionUnavailableError",
    "VideoCompressionFailedError",
]

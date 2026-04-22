"""
Document parsers for converting files to chunks.
"""

from picho.builtin.tool.extension.read.parser.types import (
    Chunk,
    ChunkType,
    Image,
    Metadata,
)
from picho.builtin.tool.extension.read.parser.parser_docx import parse_docx
from picho.builtin.tool.extension.read.parser.parser_pdf import parse_pdf

DOCUMENT_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}

SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(DOCUMENT_PARSERS)

__all__ = [
    "Chunk",
    "ChunkType",
    "Image",
    "Metadata",
    "DOCUMENT_PARSERS",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "parse_docx",
    "parse_pdf",
]

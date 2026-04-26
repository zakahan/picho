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
from picho.builtin.tool.extension.read.parser.parser_audio import (
    AUDIO_EXTENSIONS,
    AudioTranscript,
    AudioUtterance,
    get_audio_asr_provider,
    parse_audio,
)
from picho.builtin.tool.extension.read.parser.audio import (
    MockAudioAsrProvider,
    VolcengineAudioAsrProvider,
)

DOCUMENT_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}

SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(DOCUMENT_PARSERS)
SUPPORTED_AUDIO_EXTENSIONS = AUDIO_EXTENSIONS
SUPPORTED_CONVERTIBLE_EXTENSIONS = (
    SUPPORTED_DOCUMENT_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS
)

__all__ = [
    "Chunk",
    "ChunkType",
    "Image",
    "Metadata",
    "AUDIO_EXTENSIONS",
    "AudioTranscript",
    "AudioUtterance",
    "DOCUMENT_PARSERS",
    "get_audio_asr_provider",
    "MockAudioAsrProvider",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_CONVERTIBLE_EXTENSIONS",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "VolcengineAudioAsrProvider",
    "parse_audio",
    "parse_docx",
    "parse_pdf",
]

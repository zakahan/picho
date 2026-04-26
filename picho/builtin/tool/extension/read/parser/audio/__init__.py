"""
Audio ASR provider implementations.
"""

from picho.builtin.tool.extension.read.parser.audio.mock import MockAudioAsrProvider
from picho.builtin.tool.extension.read.parser.audio.volcengine import (
    VolcengineAudioAsrProvider,
)

__all__ = [
    "MockAudioAsrProvider",
    "VolcengineAudioAsrProvider",
]

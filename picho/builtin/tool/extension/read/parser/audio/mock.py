"""
Mock audio ASR provider.
"""

from pathlib import Path

from picho.builtin.tool.extension.read.parser.parser_audio import (
    AudioTranscript,
    AudioUtterance,
)
from picho.config import ReadAudioAsrConfig


class MockAudioAsrProvider:
    name = "mock"

    def transcribe(self, file_path: str, config: ReadAudioAsrConfig) -> AudioTranscript:
        del config
        path = Path(file_path)
        text = (
            f"[Mock ASR transcript for {path.name}. "
            "No external speech recognition service was called.]"
        )
        return AudioTranscript(
            provider=self.name,
            text=text,
            utterances=[
                AudioUtterance(text=text, start_time=0, end_time=0),
            ],
        )

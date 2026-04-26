"""
Audio parser entrypoint for converting speech files to markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from picho.config import ReadAudioAsrConfig


AUDIO_EXTENSIONS = frozenset({".mp3", ".wav"})


@dataclass
class AudioUtterance:
    text: str
    start_time: int | None = None
    end_time: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioTranscript:
    provider: str
    text: str
    duration: int | None = None
    task_id: str | None = None
    utterances: list[AudioUtterance] = field(default_factory=list)


class AudioAsrProvider(Protocol):
    name: str

    def transcribe(self, file_path: str, config: ReadAudioAsrConfig) -> AudioTranscript:
        """Transcribe a local audio file."""


def parse_audio(file_path: str, config: ReadAudioAsrConfig | None = None) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio file type: {ext}")

    asr_config = config or ReadAudioAsrConfig()
    provider = get_audio_asr_provider(asr_config.provider)
    transcript = provider.transcribe(file_path, asr_config)
    return transcript_to_markdown(file_path, transcript, asr_config)


def transcript_to_markdown(
    file_path: str,
    transcript: AudioTranscript,
    config: ReadAudioAsrConfig,
) -> str:
    lines = [
        "# Audio transcription",
        "",
        f"- File: {Path(file_path).name}",
        f"- Provider: {transcript.provider}",
    ]
    if transcript.task_id:
        lines.append(f"- Task ID: {transcript.task_id}")
    if transcript.duration is not None:
        lines.append(f"- Duration: {transcript.duration} ms")

    lines.extend(["", "## Transcript", "", transcript.text.strip()])

    if config.include_utterances and transcript.utterances:
        lines.extend(["", "## Utterances", ""])
        for utterance in transcript.utterances:
            timestamp = _format_utterance_timestamp(utterance)
            prefix = f"- {timestamp} " if timestamp else "- "
            lines.append(f"{prefix}{utterance.text.strip()}")

    return "\n".join(lines).rstrip() + "\n"


def get_audio_asr_provider(name: str) -> AudioAsrProvider:
    if name == "mock":
        from picho.builtin.tool.extension.read.parser.audio.mock import (
            MockAudioAsrProvider,
        )

        return MockAudioAsrProvider()

    if name == "volcengine":
        from picho.builtin.tool.extension.read.parser.audio.volcengine import (
            VolcengineAudioAsrProvider,
        )

        return VolcengineAudioAsrProvider()

    raise ValueError(f"Unsupported audio ASR provider: {name}")


def _format_utterance_timestamp(utterance: AudioUtterance) -> str:
    if utterance.start_time is None or utterance.end_time is None:
        return ""
    return (
        f"[{_ms_to_time(utterance.start_time)} --> {_ms_to_time(utterance.end_time)}]"
    )


def _ms_to_time(ms: int) -> str:
    seconds = ms // 1000
    millis = ms % 1000
    minutes = seconds // 60
    seconds %= 60
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

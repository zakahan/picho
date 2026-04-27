from __future__ import annotations

import asyncio
from pathlib import Path

from picho.builtin.tool import HostExecutor, create_read_tool
from picho.builtin.tool.extension.read.convert import convert_to_markdown
from picho.builtin.tool.extension.read.parser.audio.volcengine import (
    VolcengineAudioAsrProvider,
)
from picho.builtin.tool.extension.read.parser.parser_audio import (
    parse_audio,
)
from picho.config import ReadAudioAsrConfig, ReadToolConfig


def _run_read(tool, path: str, **params):
    if tool.execute is None:
        raise RuntimeError("Read tool execute function is not available")
    return asyncio.run(tool.execute("test-read", {"path": path, **params}))


def test_parse_audio_uses_mock_provider_for_mp3(tmp_path: Path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake mp3")

    markdown = parse_audio(str(audio_path), ReadAudioAsrConfig(provider="mock"))

    assert "# Audio transcription" in markdown
    assert "- File: sample.mp3" in markdown
    assert "- Provider: mock" in markdown
    assert "Mock ASR transcript for sample.mp3" in markdown


def test_read_tool_transcribes_wav_with_mock_provider(tmp_path: Path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake wav")
    tool = create_read_tool(
        HostExecutor(cwd=str(tmp_path)),
        read_config=ReadToolConfig(audio_asr=ReadAudioAsrConfig(provider="mock")),
    )

    result = _run_read(tool, "sample.wav")

    assert result.is_error is False
    assert result.content[0].type == "text"
    assert "Mock ASR transcript for sample.wav" in result.content[0].text
    assert "[Converted from .wav." in result.content[0].text


def test_audio_cache_variant_includes_asr_provider(tmp_path: Path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake mp3")

    mock_markdown = convert_to_markdown(
        str(audio_path),
        str(tmp_path),
        ReadToolConfig(audio_asr=ReadAudioAsrConfig(provider="mock")),
    )

    assert "Provider: mock" in mock_markdown
    cache_dirs = list((tmp_path / "files").iterdir())
    assert len(cache_dirs) == 1


def test_read_audio_asr_config_parses_nested_volcengine_options():
    config = ReadToolConfig.from_dict(
        {
            "audio_asr": {
                "provider": "volcengine",
                "language": "zh-CN",
                "enable_punc": True,
                "timeout_seconds": 30,
                "volcengine": {
                    "tos_bucket": "audio-bucket",
                    "tos_region": "cn-shanghai",
                    "sample_rate": 8000,
                },
            }
        }
    )

    assert config.audio_asr.provider == "volcengine"
    assert config.audio_asr.language == "zh-CN"
    assert config.audio_asr.enable_punc is True
    assert config.audio_asr.timeout_seconds == 30
    assert config.audio_asr.volcengine.tos_bucket == "audio-bucket"
    assert config.audio_asr.volcengine.tos_region == "cn-shanghai"
    assert config.audio_asr.volcengine.sample_rate == 8000


def test_volcengine_provider_uploads_then_transcribes(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake wav")

    class FakeUploader:
        def upload(self, file_path: str) -> str:
            assert file_path == str(audio_path)
            return "https://example.com/sample.wav"

    def fake_build_uploader(self, config):
        del self, config
        return FakeUploader()

    def fake_transcribe_url(self, url, file_path, config):
        del self, config
        assert url == "https://example.com/sample.wav"
        assert file_path == str(audio_path)
        return {
            "status": "success",
            "task_id": "task-1",
            "data": {
                "result": {
                    "text": "hello from volcengine",
                    "utterances": [
                        {
                            "start_time": 0,
                            "end_time": 1200,
                            "text": "hello from volcengine",
                        }
                    ],
                },
                "audio_info": {"duration": 1200},
            },
        }

    monkeypatch.setattr(
        VolcengineAudioAsrProvider,
        "_build_uploader",
        fake_build_uploader,
    )
    monkeypatch.setattr(
        VolcengineAudioAsrProvider,
        "_transcribe_url",
        fake_transcribe_url,
    )

    markdown = parse_audio(
        str(audio_path),
        ReadAudioAsrConfig(provider="volcengine"),
    )

    assert "- Provider: volcengine" in markdown
    assert "- Task ID: task-1" in markdown
    assert "- Duration: 1200 ms" in markdown
    assert "hello from volcengine" in markdown
    assert "- [00:00.000 --> 00:01.200] hello from volcengine" in markdown

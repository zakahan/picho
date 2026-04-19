"""
Video preparation module for read tool.

Oversized videos can be compressed into a cached MP4 file before they are
forwarded to the model provider.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from picho.logger import get_logger
from picho.tool.executor import Executor

_log = get_logger(__name__)

COMPRESSED_VIDEO_FILE = "compressed.mp4"
METADATA_FILE = "metadata.json"
CACHE_VERSION = 2


class VideoCompressionUnavailableError(RuntimeError):
    """Raised when video compression is configured but not available."""


class VideoCompressionFailedError(RuntimeError):
    """Raised when video compression could not produce a valid result."""

    def __init__(
        self,
        message: str,
        *,
        attempts: list["CompressionAttempt"] | None = None,
        original_size_bytes: int | None = None,
        limit_bytes: int | None = None,
    ):
        super().__init__(message)
        self.attempts = attempts or []
        self.original_size_bytes = original_size_bytes
        self.limit_bytes = limit_bytes

    def to_user_message(self) -> str:
        lines = [
            "This video is too large to read directly, and picho could not shrink it enough for the configured upload limit.",
        ]

        if self.original_size_bytes is not None and self.limit_bytes is not None:
            lines.append(
                f"Source size: {_format_size(self.original_size_bytes)}. Configured limit: {_format_size(self.limit_bytes)}."
            )

        if self.attempts:
            lines.append("Compression attempts:")
            for attempt in self.attempts:
                attempt_line = (
                    f"- {attempt.profile_name}: "
                    f"{attempt.max_width}x{attempt.max_height}, "
                    f"video {attempt.video_bitrate_kbps}k, "
                    f"audio {attempt.audio_bitrate_kbps}k"
                )
                if attempt.output_size_bytes is not None:
                    attempt_line += (
                        f", output {_format_size(attempt.output_size_bytes)}"
                    )
                if attempt.failure_reason:
                    attempt_line += f" ({attempt.failure_reason})"
                lines.append(attempt_line)

        lines.append(
            "Please compress or split the video manually, then try reading it again."
        )
        return "\n".join(lines)


@dataclass
class VideoPreparationResult:
    source_path: str
    output_path: str
    cache_dir: Path
    original_size_bytes: int
    output_size_bytes: int
    limit_bytes: int
    was_compressed: bool
    used_cache: bool


@dataclass
class CompressionPlan:
    total_bitrate_kbps: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    max_width: int
    max_height: int
    preset: str = "veryfast"


@dataclass
class CompressionAttempt:
    profile_name: str
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    max_width: int
    max_height: int
    output_size_bytes: int | None = None
    failure_reason: str | None = None


def get_video_cache_dir(file_path: str, workspace: str, limit_bytes: int) -> Path:
    """
    Get cache directory path for a prepared video.

    Cache key is based on file path, mtime and compression settings so the cache
    is automatically invalidated when source content or policy changes.
    """
    p = Path(file_path)
    cache_key = hashlib.md5(
        f"video:{file_path}:{p.stat().st_mtime}:{limit_bytes}:{CACHE_VERSION}".encode()
    ).hexdigest()
    return Path(workspace) / ".picho" / "cache" / "files" / cache_key


def _read_cached_result(
    cache_dir: Path, limit_bytes: int
) -> VideoPreparationResult | None:
    video_path = cache_dir / COMPRESSED_VIDEO_FILE
    metadata_path = cache_dir / METADATA_FILE
    if not video_path.exists() or not metadata_path.exists():
        return None

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output_size_bytes = video_path.stat().st_size
    if output_size_bytes > limit_bytes:
        return None

    return VideoPreparationResult(
        source_path=metadata["source_file"],
        output_path=str(video_path),
        cache_dir=cache_dir,
        original_size_bytes=metadata["original_size_bytes"],
        output_size_bytes=output_size_bytes,
        limit_bytes=limit_bytes,
        was_compressed=True,
        used_cache=True,
    )


def _save_metadata(
    cache_dir: Path,
    source_file: str,
    original_size_bytes: int,
    output_size_bytes: int,
    limit_bytes: int,
    plan: CompressionPlan,
    duration_seconds: float,
) -> None:
    metadata = {
        "source_file": source_file,
        "file_name": Path(source_file).name,
        "original_size_bytes": original_size_bytes,
        "output_size_bytes": output_size_bytes,
        "limit_bytes": limit_bytes,
        "duration_seconds": duration_seconds,
        "video_bitrate_kbps": plan.video_bitrate_kbps,
        "audio_bitrate_kbps": plan.audio_bitrate_kbps,
        "max_width": plan.max_width,
        "max_height": plan.max_height,
        "preset": plan.preset,
        "cache_version": CACHE_VERSION,
        "converted_at": datetime.now().isoformat(),
    }
    (cache_dir / METADATA_FILE).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes / 1024 / 1024:.1f}MB"


def _shell_escape(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


async def _ensure_command(executor: Executor, command: str, signal: Any = None) -> bool:
    result = await executor.exec(f"command -v {command}", signal=signal)
    return result.code == 0 and bool(result.stdout.strip())


async def _probe_duration_seconds(
    file_path: str, executor: Executor, signal: Any = None
) -> float:
    result = await executor.exec(
        "ffprobe -v error "
        "-show_entries format=duration "
        "-of default=noprint_wrappers=1:nokey=1 "
        f"{_shell_escape(file_path)}",
        signal=signal,
    )
    if result.code != 0:
        raise VideoCompressionFailedError(
            f"ffprobe failed while reading duration: {result.stderr.strip() or 'unknown error'}"
        )

    try:
        duration_seconds = float(result.stdout.strip())
    except ValueError as exc:
        raise VideoCompressionFailedError(
            f"ffprobe returned invalid duration: {result.stdout.strip()!r}"
        ) from exc

    if duration_seconds <= 0:
        raise VideoCompressionFailedError(
            "Video duration must be greater than 0 seconds"
        )

    return duration_seconds


def _build_compression_plan(
    duration_seconds: float, limit_bytes: int, aggressive: bool
) -> CompressionPlan:
    # Reserve a bit of space for container overhead and metadata.
    target_bytes = int(limit_bytes * (0.90 if aggressive else 0.94))
    total_bitrate_kbps = max(
        180, int(target_bytes * 8 / max(duration_seconds, 1.0) / 1000)
    )

    if total_bitrate_kbps <= 240:
        audio_bitrate_kbps = 32
    elif total_bitrate_kbps <= 420:
        audio_bitrate_kbps = 48
    else:
        audio_bitrate_kbps = 64 if not aggressive else 48

    min_video_bitrate_kbps = 96 if aggressive else 160
    video_bitrate_kbps = max(
        min_video_bitrate_kbps, total_bitrate_kbps - audio_bitrate_kbps
    )
    total_bitrate_kbps = video_bitrate_kbps + audio_bitrate_kbps

    return CompressionPlan(
        total_bitrate_kbps=total_bitrate_kbps,
        video_bitrate_kbps=video_bitrate_kbps,
        audio_bitrate_kbps=audio_bitrate_kbps,
        max_width=640 if aggressive else 854,
        max_height=360 if aggressive else 480,
        preset="veryfast",
    )


def _build_scale_filter(plan: CompressionPlan) -> str:
    return (
        f"scale={plan.max_width}:{plan.max_height}:"
        "force_original_aspect_ratio=decrease:"
        "force_divisible_by=2"
    )


def _build_ffmpeg_command(
    source_path: str, output_path: str, plan: CompressionPlan
) -> str:
    maxrate_kbps = int(plan.video_bitrate_kbps * 1.15)
    bufsize_kbps = int(plan.video_bitrate_kbps * 2)
    return (
        "ffmpeg -y "
        f"-i {_shell_escape(source_path)} "
        "-map 0:v:0 -map 0:a? "
        f'-vf "{_build_scale_filter(plan)}" '
        "-c:v libx264 "
        f"-preset {plan.preset} "
        f"-b:v {plan.video_bitrate_kbps}k "
        f"-maxrate {maxrate_kbps}k "
        f"-bufsize {bufsize_kbps}k "
        "-pix_fmt yuv420p "
        "-movflags +faststart "
        "-c:a aac "
        f"-b:a {plan.audio_bitrate_kbps}k "
        "-ac 2 "
        "-sn "
        f"{_shell_escape(output_path)}"
    )


def _summarize_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return "unknown ffmpeg error"

    interesting_prefixes = (
        "[libx264",
        "[vost",
        "[vf",
        "[out",
        "Error while",
        "Could not open encoder",
        "Nothing was written",
        "Conversion failed!",
    )
    interesting = [line for line in lines if line.startswith(interesting_prefixes)]
    if interesting:
        return interesting[0]
    return lines[-1]


async def _compress_video(
    source_path: str,
    output_path: str,
    executor: Executor,
    duration_seconds: float,
    limit_bytes: int,
    original_size_bytes: int,
    signal: Any = None,
) -> tuple[int, CompressionPlan]:
    attempts: list[CompressionAttempt] = []
    for aggressive in (False, True):
        plan = _build_compression_plan(
            duration_seconds, limit_bytes, aggressive=aggressive
        )
        attempt = CompressionAttempt(
            profile_name="aggressive" if aggressive else "standard",
            video_bitrate_kbps=plan.video_bitrate_kbps,
            audio_bitrate_kbps=plan.audio_bitrate_kbps,
            max_width=plan.max_width,
            max_height=plan.max_height,
        )
        _log.info(
            "Compressing oversized video for read: "
            f"source={Path(source_path).name} "
            f"target_limit={_format_size(limit_bytes)} "
            f"duration={duration_seconds:.1f}s "
            f"video_bitrate={plan.video_bitrate_kbps}k "
            f"audio_bitrate={plan.audio_bitrate_kbps}k "
            f"max_width={plan.max_width} "
            f"max_height={plan.max_height}"
        )

        result = await executor.exec(
            _build_ffmpeg_command(source_path, output_path, plan),
            signal=signal,
        )
        if result.code != 0:
            attempt.failure_reason = _summarize_ffmpeg_error(result.stderr)
            attempts.append(attempt)
            raise VideoCompressionFailedError(
                "ffmpeg failed during video compression",
                attempts=attempts,
                original_size_bytes=original_size_bytes,
                limit_bytes=limit_bytes,
            )

        output_file = Path(output_path)
        if not output_file.exists():
            attempt.failure_reason = "compressed video was not generated"
            attempts.append(attempt)
            raise VideoCompressionFailedError("Compressed video was not generated")

        output_size_bytes = output_file.stat().st_size
        attempt.output_size_bytes = output_size_bytes
        _log.info(
            "Video compression completed: "
            f"source={Path(source_path).name} "
            f"output={output_file.name} "
            f"size={_format_size(output_size_bytes)} "
            f"limit={_format_size(limit_bytes)} "
            f"aggressive={aggressive}"
        )

        if output_size_bytes <= limit_bytes:
            return output_size_bytes, plan

        attempt.failure_reason = "still exceeds upload limit"
        attempts.append(attempt)
        _log.warning(
            "Compressed video still exceeds limit, retrying with a more aggressive plan: "
            f"size={_format_size(output_size_bytes)} "
            f"limit={_format_size(limit_bytes)}"
        )

    raise VideoCompressionFailedError(
        "Compressed video still exceeds the configured size limit after retry",
        attempts=attempts,
        original_size_bytes=original_size_bytes,
        limit_bytes=limit_bytes,
    )


async def prepare_video_for_read(
    file_path: str,
    workspace: str,
    executor: Executor,
    limit_bytes: int,
    signal: Any = None,
) -> VideoPreparationResult:
    source_path = str(Path(file_path).resolve())
    original_size_bytes = Path(source_path).stat().st_size

    if original_size_bytes <= limit_bytes:
        return VideoPreparationResult(
            source_path=source_path,
            output_path=source_path,
            cache_dir=get_video_cache_dir(source_path, workspace, limit_bytes),
            original_size_bytes=original_size_bytes,
            output_size_bytes=original_size_bytes,
            limit_bytes=limit_bytes,
            was_compressed=False,
            used_cache=False,
        )

    ffmpeg_available = await _ensure_command(executor, "ffmpeg", signal=signal)
    ffprobe_available = await _ensure_command(executor, "ffprobe", signal=signal)
    if not ffmpeg_available or not ffprobe_available:
        raise VideoCompressionUnavailableError(
            "ffmpeg and ffprobe must be installed and available in PATH"
        )

    cache_dir = get_video_cache_dir(source_path, workspace, limit_bytes)
    cached = _read_cached_result(cache_dir, limit_bytes)
    if cached is not None:
        _log.info(
            "Using cached compressed video for read: "
            f"source={Path(source_path).name} "
            f"cache_dir={cache_dir}"
        )
        return cached

    cache_dir.mkdir(parents=True, exist_ok=True)
    duration_seconds = await _probe_duration_seconds(
        source_path, executor, signal=signal
    )
    output_path = str(cache_dir / COMPRESSED_VIDEO_FILE)
    output_size_bytes, plan = await _compress_video(
        source_path=source_path,
        output_path=output_path,
        executor=executor,
        duration_seconds=duration_seconds,
        limit_bytes=limit_bytes,
        original_size_bytes=original_size_bytes,
        signal=signal,
    )
    _save_metadata(
        cache_dir=cache_dir,
        source_file=source_path,
        original_size_bytes=original_size_bytes,
        output_size_bytes=output_size_bytes,
        limit_bytes=limit_bytes,
        plan=plan,
        duration_seconds=duration_seconds,
    )

    return VideoPreparationResult(
        source_path=source_path,
        output_path=output_path,
        cache_dir=cache_dir,
        original_size_bytes=original_size_bytes,
        output_size_bytes=output_size_bytes,
        limit_bytes=limit_bytes,
        was_compressed=True,
        used_cache=False,
    )

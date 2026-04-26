"""
Document conversion module for reading PDF and DOCX files.
Converts documents to markdown format with caching support.

Cache structure:
    .picho/
    └── cache/
        └── files/
            └── {cache_key}/
                ├── document.md
                ├── metadata.json
                ├── image_0.png
                ├── image_1.png
                └── ...
"""

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path

from picho.config import ReadToolConfig
from picho.builtin.tool.extension.read.parser import (
    Chunk,
    ChunkType,
    DOCUMENT_PARSERS,
    SUPPORTED_AUDIO_EXTENSIONS,
    parse_audio,
)


DOCUMENT_FILE = "document.md"
METADATA_FILE = "metadata.json"


def get_cache_dir(
    file_path: str,
    workspace: str,
    variant: str | None = None,
) -> Path:
    """
    Get cache directory path for a file.

    Cache key is based on file path + modification time.
    When file is modified, mtime changes -> cache_key changes -> new cache dir.
    """
    p = Path(file_path)
    mtime = p.stat().st_mtime
    variant_key = f":{variant}" if variant else ""
    cache_key = hashlib.md5(f"{file_path}:{mtime}{variant_key}".encode()).hexdigest()
    cache_dir = Path(workspace) / ".picho" / "cache" / "files" / cache_key
    return cache_dir


def read_cache(cache_dir: Path) -> str | None:
    """Read cached markdown content if exists."""
    document_path = cache_dir / DOCUMENT_FILE
    if document_path.exists():
        return document_path.read_text(encoding="utf-8")
    return None


def save_cache(cache_dir: Path, content: str, source_file: str, file_type: str) -> None:
    """Save markdown content and metadata to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    document_path = cache_dir / DOCUMENT_FILE
    document_path.write_text(content, encoding="utf-8")

    p = Path(source_file)
    metadata = {
        "source_file": str(p),
        "file_name": p.name,
        "file_type": file_type,
        "mtime": p.stat().st_mtime,
        "converted_at": datetime.now().isoformat(),
    }
    metadata_path = cache_dir / METADATA_FILE
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def chunks_to_markdown(chunks: list[Chunk]) -> str:
    """Convert chunks to markdown format."""
    markdown_lines = []

    for chunk in chunks:
        if chunk.type == ChunkType.TEXT.value:
            text = chunk.text.strip()
            if not text:
                continue
            if chunk.metadata.is_title and chunk.metadata.title_level > 0:
                level = min(chunk.metadata.title_level, 6)
                markdown_lines.append(f"{'#' * level} {text}")
            else:
                markdown_lines.append(text)

        elif chunk.type == ChunkType.IMAGE.value:
            if chunk.image.type == "image_path" and chunk.image.path:
                markdown_lines.append(f"![image]({chunk.image.path})")

        elif chunk.type == ChunkType.TABLE.value:
            if chunk.text.strip():
                lines = chunk.text.strip().split("\n")
                table_lines = []
                for line in lines:
                    if "\t|" in line:
                        table_line = line.replace("\t|", "|")
                        table_lines.append(f"|{table_line}|")
                    else:
                        table_lines.append(f"|{line}|")

                if table_lines:
                    header = table_lines[0]
                    col_count = len(header.split("|")) - 2
                    separator = "|" + "|".join(["---" for _ in range(col_count)]) + "|"
                    table_lines.insert(1, separator)
                    markdown_lines.extend(table_lines)

    return "\n\n".join(markdown_lines)


async def convert_to_markdown_async(
    file_path: str,
    workspace: str,
    read_config: ReadToolConfig | None = None,
    signal=None,
) -> str:
    """
    Run document conversion in a worker thread so abort signals can interrupt the
    await path even when PDF/DOCX parsing is CPU/IO heavy.
    """
    if read_config is None:
        conversion_task = asyncio.create_task(
            asyncio.to_thread(convert_to_markdown, file_path, workspace)
        )
    else:
        conversion_task = asyncio.create_task(
            asyncio.to_thread(convert_to_markdown, file_path, workspace, read_config)
        )
    if signal is None:
        return await conversion_task

    signal_task = asyncio.create_task(signal.wait())
    try:
        done, pending = await asyncio.wait(
            [conversion_task, signal_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if signal_task in done and signal.is_set():
            conversion_task.cancel()
            raise asyncio.CancelledError("Operation aborted by user")

        return await conversion_task
    finally:
        if not signal_task.done():
            signal_task.cancel()
            try:
                await signal_task
            except asyncio.CancelledError:
                pass


def convert_to_markdown(
    file_path: str,
    workspace: str,
    read_config: ReadToolConfig | None = None,
) -> str:
    """
    Convert a supported rich file to markdown.

    Args:
        file_path: Path to the file to convert
        workspace: Workspace path for cache storage

    Returns:
        Markdown content as string
    """
    cache_variant = get_cache_variant(file_path, read_config)
    cache_dir = get_cache_dir(file_path, workspace, variant=cache_variant)

    cached = read_cache(cache_dir)
    if cached is not None:
        return cached

    ext = Path(file_path).suffix.lower()
    image_dir = str(cache_dir)

    if ext in SUPPORTED_AUDIO_EXTENSIONS:
        markdown = parse_audio(
            file_path,
            read_config.audio_asr if read_config else None,
        )
    else:
        parser = DOCUMENT_PARSERS.get(ext)
        if parser is None:
            raise ValueError(f"Unsupported file type: {ext}")
        chunks = parser(file_path, image_dir)
        markdown = chunks_to_markdown(chunks)

    save_cache(cache_dir, markdown, file_path, ext)

    return markdown


def get_cache_variant(
    file_path: str,
    read_config: ReadToolConfig | None = None,
) -> str | None:
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        return None

    audio_config = read_config.audio_asr if read_config else None
    if audio_config is None:
        return "audio:provider=mock"

    return "|".join(
        [
            "audio",
            f"provider={audio_config.provider}",
            f"language={audio_config.language or ''}",
            f"enable_punc={audio_config.enable_punc}",
            f"enable_itn={audio_config.enable_itn}",
            f"enable_ddc={audio_config.enable_ddc}",
            f"enable_speaker_info={audio_config.enable_speaker_info}",
            f"include_utterances={audio_config.include_utterances}",
            f"include_words={audio_config.include_words}",
            f"vad_segment={audio_config.vad_segment}",
        ]
    )

# Builtin Module

Built-in tools and skills for picho.

## Overview

This module provides built-in tools and skills that can be used by AI agents out of the box.

## Architecture

```
builtin/
├── __init__.py          # Module exports
├── decorator.py         # @pi_tool decorator
├── security.py          # Security utilities
├── tool/                # Built-in tools
│   ├── __init__.py
│   ├── read.py          # File reading tool
│   ├── write.py         # File writing tool
│   ├── edit.py          # File editing tool
│   └── bash.py          # Bash execution tool
└── skill/               # Built-in skills
    ├── __init__.py
    ├── code-review/     # Code review skill
    ├── debug/           # Debug skill
    └── skill-creator/   # Skill creator skill
```

## Built-in Tools

### read - Read File

Read file contents with support for text, images, videos, audio, PDF, and DOCX:

```python
# Parameters
{
    "path": "File path (relative or absolute)",
    "offset": "Starting line number (optional, 1-based)",
    "limit": "Maximum lines to read (optional)"
}
```

Features:
- Auto-truncation for large files (default 2000 lines or 50KB)
- Image file support (jpg, png, gif, webp)
- Video file support (mp4, mov, avi, mkv, webm)
- PDF/DOCX are converted to markdown and cached under `.picho/cache/files`
- WAV/MP3 are transcribed to markdown and cached under `.picho/cache/files`
- Video compression is enabled by default: when a video exceeds the configured limit, picho compresses it with `ffmpeg` while keeping audio; set `tool_config.read.video_compression.enabled=false` to disable it
- Read extensions can handle custom file types
- Pagination support

Behavior:
- Missing files and other normal tool errors are returned as error text results instead of Python tracebacks
- Abort signals propagate as cancellation so the agent loop can emit the standard aborted tool result
- PDF/DOCX and audio conversion now respond to aborts while waiting on conversion, even though the worker thread may finish in the background

Audio ASR config example:

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "audio_asr": {
            "provider": "volcengine",
            "language": "zh-CN",
            "enable_punc": true,
            "volcengine": {
              "tos_bucket": "my-bucket",
              "tos_region": "cn-beijing"
            }
          }
        }
      }
    }
  }
}
```

Notes:
- `audio_asr.provider` can be `mock` or `volcengine`; the default is `mock`.
- The Volcengine provider uploads the local audio to TOS and then submits the public URL to Doubao Speech ASR.
- Volcengine credentials are read from environment variables: `VOLCENGINE_ACCESS_KEY`, `VOLCENGINE_SECRET_KEY`, and `VOLCENGINE_SPEECH_API_KEY`.
- If `audio_asr.volcengine.tos_bucket` is omitted, `DEFAULT_TOS_BUCKET` is used.
- Provider-specific docs live under `tool/extension/read/parser/audio/*.md`.

Video compression config example:

```json
{
  "path": {
    "cache": "."
  },
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "video_compression": {
            "enabled": true,
            "trigger_size_mb": 512
          }
        }
      }
    }
  }
}
```

Notes:
- If the config is missing, automatic video compression is enabled by default; set `enabled=false` to use the original read path
- Compression only runs when the video is larger than `trigger_size_mb`
- `ffmpeg` and `ffprobe` must be installed on the user's machine
- Compressed outputs are cached and reused while the source file is unchanged
- `path.cache` is optional; by default picho uses `path.base`, relative paths resolve from `path.base`, and absolute paths are used as-is

Custom read extension example:

```python
from pathlib import Path

from picho.builtin.tool.extension.read import ReadExtension, ReadExtensionContext
from picho.provider.types import TextContent
from picho.tool import ToolResult


def read_csv(context: ReadExtensionContext) -> ToolResult:
    content = Path(context.resolved_path).read_text(encoding="utf-8")
    return ToolResult(
        content=[TextContent(type="text", text=content)]
    )


READ_EXTENSIONS = [
    ReadExtension(
        name="csv-reader",
        extensions=[".csv"],
        execute=read_csv,
    )
]
```

Matching config:

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "extensions": [
            ".picho/read_extensions/csv_reader.py"
          ]
        }
      }
    }
  }
}
```

Override built-in readers:
- Custom read extensions are matched before built-in handlers.
- Registering an extension for `.pdf` or `.docx` lets you replace the default document-to-markdown reader.
- This is useful when you want a different parser, OCR flow, layout cleanup, or post-processing strategy.

### write - Write File

Create or overwrite files:

```python
# Parameters
{
    "path": "File path",
    "content": "File content"
}
```

Features:
- Auto-create parent directories
- Overwrite existing files
- Restricts writes to files inside the workspace

Behavior:
- Validation and write failures are returned as error text results instead of Python tracebacks
- Abort signals propagate as cancellation so the agent loop can emit the standard aborted tool result

### edit - Edit File

Make precise edits to files:

```python
# Parameters
{
    "path": "File path",
    "oldText": "Text to replace (must match exactly)",
    "newText": "New text"
}
```

Features:
- Exact text matching
- Uniqueness requirement
- Preserves other file content
- Restricts edits to files inside the workspace

Behavior:
- Validation failures, missing matches, and write failures are returned as error text results instead of Python tracebacks
- Abort signals propagate as cancellation so the agent loop can emit the standard aborted tool result

### bash - Execute Command

Execute bash commands:

```python
# Parameters
{
    "command": "Bash command",
    "timeout": "Timeout in seconds (optional)"
}
```

Features:
- Execute in specified workspace
- Auto-truncate output (default 2000 lines or 50KB)
- Timeout control

Behavior:
- Non-zero exit codes and execution failures are returned as error text results instead of Python tracebacks
- Abort signals propagate as cancellation so the agent loop can emit the standard aborted tool result

## Built-in Skills

### code-review

Code review skill for merge requests and code diffs:

```python
# Load the skill
from picho.builtin.skill import load_builtin_skills

result = load_builtin_skills(["code-review"])
```

### debug

Debug skill for troubleshooting complex issues:

```python
result = load_builtin_skills(["debug"])
```

### skill-creator

Skill for creating new skills:

```python
result = load_builtin_skills(["skill-creator"])
```

## Usage

### Create All Built-in Tools

```python
from picho.builtin.tool import create_builtin_tools, HostExecutor

executor = HostExecutor(cwd="/path/to/workspace")
tools = create_builtin_tools(executor)
```

### Create Individual Tools

```python
from picho.builtin.tool import (
    create_read_tool,
    create_write_tool,
    create_edit_tool,
    create_bash_tool,
    HostExecutor,
)

executor = HostExecutor(cwd="/path/to/workspace")

read_tool = create_read_tool(executor)
write_tool = create_write_tool(executor)
edit_tool = create_edit_tool(executor)
bash_tool = create_bash_tool(executor)
```

### Load Built-in Skills

```python
from picho.builtin.skill import load_builtin_skills

# Load all built-in skills
result = load_builtin_skills()

# Load specific skills
result = load_builtin_skills(["code-review", "debug"])

for skill in result.skills:
    print(f"Loaded: {skill.name}")
```

### Using @pi_tool Decorator

Create custom tools with the decorator:

```python
from picho.builtin import pi_tool


@pi_tool(
    name="my_tool",
    description="My custom tool",
)
async def my_tool_execute(params: dict) -> str:
    return "Result"
```

## License

MIT

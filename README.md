# picho

`picho` is a minimal Agent framework. It originally started as a Python implementation of [`pi-mono`](https://github.com/badlogic/pi-mono), while also borrowing some ideas from [`google-adk`](https://github.com/google/adk-python). It later grew with more extensions, mainly for general execution-oriented Agent scenarios and multimodal use cases. `picho` puts special emphasis on file reading, with the goal of building an Agent in a more direct way and with less machinery.

## Design Philosophy

The design philosophy of `picho` is to be as **direct** and as **simple** as possible.

- Direct

In many frameworks, reading a PDF or DOCX file takes two steps: find the appropriate skill, parse the file, and then let a read skill consume the parsed output. `picho` takes a more direct approach by optimizing the `read` tool itself:

- Supports text and images.
- After installing the extension dependencies, it can read PDF and DOCX directly.
- Video support is also specially optimized. `picho` includes a dedicated video compression step that is transparent to the model. This extends the practical size limit for video reading, allowing the model to handle larger files after compression.
  - Note: this optimization currently works only with Ark models.
- Support for more file types such as audio and PPTX is planned.

For the extension layer, you do not have to use the built-in `read` extensions. You can write your own read extensions to support new file types, or replace the existing read pipeline altogether.

And if you genuinely prefer handling files through skills, that is also perfectly fine. Built-in `read` is better suited to direct, general-purpose file access, while skills are better for domain-specific workflows, multi-step processing, or more complex compositions with other tools. The two are not in conflict.

- Simple

Simplicity is one of the core design goals of `picho`, and that shows up in multiple places. The first is the Agent loop.

The core loop is inspired by `pi-mono`, and can be simplified to:

```python
while True:
    response = model(context)      # Call the LLM
    context += response            # Append response to context

    if response.tool_calls:
        results = execute(response.tool_calls)
        context += results         # Execute tools and append results
    else:
        break                      # Stop when there are no tool calls
```

The loop remains intentionally small. It avoids a heavy orchestration layer, but still leaves hook points for custom control logic inside the loop.

The same idea also appears in the extension packages. Apart from cases that truly depend on `ffmpeg` or external services, such as video compression or audio understanding, `picho` tries to keep features like PDF and DOCX handling within pure Python and avoid introducing extra third-party system dependencies.

## Quick Start

### Installation

Using `uv` is recommended:

```bash
# Install
uv add picho
# If you want native read support for PDF and DOCX
uv add picho["extra"]
```

### Usage Modes

`picho` commonly supports three usage modes: start the CLI directly from a config file, build a `Runner` dynamically in Python, or expose a `Runner` as an API service.

For the full configuration reference, field descriptions, and extension examples, see [picho/config.md](./picho/config.md).

#### 1. Configure `config.json` and start `picho chat`

This is the most direct mode: prepare a config file, then start an interactive session.

`picho chat` looks for config files in the following order:

- `.picho/config.json` in the current directory
- `config.json` in the current directory
- `~/.picho/config.json` in the user home directory

A minimal config example:

```json
{
  "path": {
    "base": ".",
    "executor": ".",
    "skills": [".picho/skills"]
  },
  "agent": {
    "model": {
      "model_provider": "ark-responses",
      "model_name": "doubao-seed-2-0-lite-260215",
      "base_url": "https://ark.cn-beijing.volces.com/api/v3",
      "api_key": "YOUR_ARK_API_KEY",
      "input_types": ["text", "image", "video"]
    },
    "instructions": "You are a concise and reliable AI assistant.",
    "builtin": {
      "tool": ["read", "write", "bash", "edit"],
      "skill": ["code-review", "debug", "skill-creator"]
    }
  },
  "session_manager": {
    "persist": true
  }
}
```

Start it with:

```bash
uv run picho chat
```

If you prefer to generate a config template first, run:

```bash
uv run picho init
```

For the full explanation of fields such as `path`, `builtin`, `tool_config.read.extensions`, and `executor`, see [picho/config.md](./picho/config.md).

#### 2. Config + Python `Runner`

If you need to build config dynamically, inject custom logic before startup, or avoid storing the full config in a JSON file, you can create a `Runner` in Python and hand it to the CLI.

Example file `my_runner.py`:

```python
import os

from picho.runner import Runner


config = {
    "path": {
        "base": ".",
        "executor": ".",
        "skills": [".picho/skills"]
    },
    "agent": {
        "model": {
            "model_provider": "ark-responses",
            "model_name": "doubao-seed-2-0-lite-260215",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": os.getenv("ARK_API_KEY"),
            "input_types": ["text", "image", "video"]
        },
        "instructions": "You are a helpful assistant.",
        "builtin": {
            "tool": ["read", "write", "bash", "edit"],
            "skill": ["code-review", "debug"]
        }
    },
    "session_manager": {
        "persist": true
    }
}

runner = Runner(config_type="dict", config=config)
```

Start it with:

```bash
uv run picho chat -r my_runner.py
```

`-r` accepts a Python file path, and that file must export a variable named `runner`.

Field definitions and configuration semantics are still documented in [picho/config.md](./picho/config.md).

#### 3. API Mode

If you need to integrate `picho` into a backend service, you can wrap `Runner` as a FastAPI application. The built-in `APIServer` already provides health checks, session management, and SSE streaming endpoints. This API design is partly inspired by `google-adk`.

Example file `api_server.py`:

```python
from picho.api.server import APIServer
from picho.runner import Runner


runner = Runner(config_type="json", config=".picho/config.json")
server = APIServer(runner, host="127.0.0.1", port=8000)
server.run()
```

Start it with:

```bash
uv run python api_server.py
```

Quick verification:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/sessions
```

If you need streaming interaction, call `/run_sse`. For the API design and endpoint details, see [picho/api/README.md](./picho/api/README.md).

## Project Structure

The project can be understood from top to bottom as: entry layer -> execution layer -> tools and skills -> session and service wrappers.

```text
picho/
├── picho/
│   ├── agent/          # Agent implementation and agent loop
│   ├── api/            # FastAPI API assembly and routes
│   ├── builtin/        # Built-in tools and built-in skills
│   ├── cli/            # picho init / picho chat / TUI
│   ├── observability/  # Observability and telemetry
│   ├── provider/       # Model provider abstractions
│   ├── runner/         # Runner, the primary orchestration entry point
│   ├── session/        # Session persistence, branching, compaction
│   ├── skills/         # Custom skill loading and formatting
│   ├── tool/           # Generic tool abstractions, executors, result handling
│   ├── utils/          # Utilities
│   ├── config.py       # Configuration model
│   └── config.md       # Configuration reference
├── tests/              # Tests
├── README.md
└── README_zh.md
```

Module responsibilities:

- [picho/cli/README.md](./picho/cli/README.md): command-line entry points, mainly `picho init` and `picho chat`.
- [picho/runner/README.md](./picho/runner/README.md): the primary programmatic entry point; organizes config, Agent, Session, skills, and tools.
- [picho/agent/README.md](./picho/agent/README.md): the Agent itself and the agent loop; responsible for model calls, tool execution, and context progression.
- [picho/provider/README.md](./picho/provider/README.md): model adapters that normalize different providers.
- [picho/session/README.md](./picho/session/README.md): session state management, persistence, branching, and context compaction.
- [picho/api/README.md](./picho/api/README.md): exposes `Runner` as HTTP / SSE endpoints for service integration.
- [picho/observability/README.md](./picho/observability/README.md): logging, serialization, and telemetry-related pieces.
- [picho/tool/README.md](./picho/tool/README.md): generic tool protocols, executors, and result truncation, not limited to built-in tools.
- [picho/builtin/README.md](./picho/builtin/README.md): out-of-the-box capabilities, including builtin tools and builtin skills.
- [picho/skills/README.md](./picho/skills/README.md): the skill loader, responsible for reading and formatting markdown + frontmatter based skills.
- [tests/README.md](./tests/README.md): testing conventions and test directory notes.

The relationship between builtin tools, skills, and built-in `read` can be summarized as follows:

- `builtin tool` is the actual executable capability layer, such as `read`, `write`, `edit`, and `bash`.
- Built-in `read` is the default first-class file reading path. It is suitable for directly reading text, images, and, through extensions, PDF, DOCX, video, and more.
- `skill` is closer to a task-level instruction template or workflow wrapper. It is suitable for code review, debugging, domain analysis, and more complex file-processing flows.
- They are complementary rather than competing: content that can be read directly should go to `read` first; when a task requires specialized procedures, extra rules, domain knowledge, or multi-step orchestration, a skill is the better fit.
  - A more personal way to describe this distinction is: built-in `read` is like a pair of eyes, used to observe the things on Earth; a file-oriented skill is more like a telescope, something you pick up when you need to look at the stars or handle more distant and specialized targets. In our view, they should serve different layers of problems. They are not in conflict, and ordinary reading should not be offloaded to a skill by default, because that would be overkill.
- `read` supports both extension and replacement: you can register new readers through `agent.builtin.tool_config.read.extensions`, and custom extensions are matched before the built-in readers. That means you can support new file types or replace the default `.pdf` and `.docx` pipelines.
- `skill` is also extensible: besides the built-in skills, you can place your own skills under `.picho/skills`, or point `path.skills` to other directories.

The core directories listed above all have their own dedicated documentation. You can read each module on demand without having to work through the entire repository first.

## Notes

The project is still in the early development stage. On the provider side, only ark-responses is fully supported, and it cannot be directly put into use yet.
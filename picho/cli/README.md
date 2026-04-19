# CLI Module

Command line interface for picho.

## Overview

This module provides the command line interface for interacting with picho, including the interactive coding TUI.

## Architecture

```
cli/
├── __init__.py              # Module exports
├── main.py                  # CLI entry point
├── chat.py                  # Chat command implementation
├── init.py                  # Init command implementation
├── tui.py                   # Textual TUI implementation
├── config.py                # CLI configuration
├── confirmation.py          # Confirmation management
└── security_callback.py     # Security callback handlers
```

## Commands

### picho init

Initialize a new project with configuration files:

```bash
picho init [OPTIONS]
```

Options:
- `-p, --provider` - LLM provider (openai-completion, openai-responses, ark-responses)
- `-m, --model` - Model name
- `--base-url` - API base URL
- `-y, --yes` - Use default values without prompting
- `--path` - Target directory (default: current directory)
- `--auto` - Use global config from ~/.picho as template

Examples:
```bash
# Interactive mode
picho init

# Quick init with OpenAI
picho init -p openai-completion -y

# Specify provider and model
picho init -p ark-responses -m doubao-pro-32k

# Initialize in specific directory
picho init --path /path/to/project

# Use global config as template
picho init --auto
```

### picho chat

Start an interactive coding session:

```bash
picho chat [OPTIONS]
```

Options:
- `-c, --config` - Path to config JSON file
- `-r, --runner` - Path to Python module that exports a `runner` variable
- `-v, --verbose` - Enable verbose logging

Examples:
```bash
# Use default config (.picho/config.json)
picho chat

# Specify config file
picho chat -c /path/to/config.json

# Use dynamic runner from Python module
picho chat -r my_runner.py
```

#### Dynamic Runner Module

You can create a Python module that dynamically builds the Runner:

```python
# my_runner.py
import os
from picho.runner import Runner

config = {
    "agent": {
        "model": {
            "model_provider": "openai-completion",
            "model_name": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": os.getenv("OPENAI_API_KEY"),
        },
        "instructions": "You are a helpful assistant.",
        "builtin": {
            "tool": ["read", "write", "bash", "edit"],
        },
    },
    "session_manager": {
        "persist": True,
    },
}

runner = Runner(config_type="dict", config=config)
```

Then run:
```bash
picho chat -r my_runner.py
```

### Interactive Commands

Inside the chat TUI:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/quit`, `/q` | Exit the session |
| `/abort` | Abort current streaming |
| `/new` | Create new session |
| `/sessions [n]` | List recent sessions |
| `/checkout <id>` | Switch to session |
| `/agent` | Show agent info |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Ctrl+C` | Abort streaming |
| `Ctrl+D` | Quit |
| `Up/Down` | Scroll chat |
| `Page Up/Down` | Scroll by page |
| `Home/End` | Scroll to top/bottom |

## Configuration

Configuration is stored in `.picho/config.json`:

```json
{
    "agent": {
        "model": {
            "model_provider": "openai-completion",
            "model_name": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "input_types": ["text", "image"]
        },
        "instructions": "You are a helpful AI assistant named picho.",
        "thinking_level": "auto",
        "builtin": {
            "tool": ["read", "write", "bash", "edit"],
            "skill": ["code-review", "debug", "skill-creator"]
        },
        "steering_mode": "one-at-a-time",
        "follow_up_mode": "one-at-a-time"
    },
    "session_manager": {
        "cwd": "/path/to/workspace",
        "persist": true
    }
}
```

### CLIConfig

```python
from picho.cli import CLIConfig, load_cli_config

config = load_cli_config()
print(config.log.console_output)
```

## TUI Features

The TUI is built with Textual and provides:

- **Scrollable Chat**: Browse full conversation history
- **Text Selection**: Select and copy text with mouse
- **Auto-expanding Input**: Input box grows with content
- **Status Bar**: Shows session info and streaming status
- **Confirmation Dialogs**: Approve/reject dangerous operations

## Usage Examples

### Quick Start

```bash
# Initialize project
picho init -p openai-completion -y

# Set API key
export OPENAI_API_KEY=your-api-key

# Start coding session
picho chat
```

### Programmatic Usage

```python
from picho.cli import CLIConfig
from picho.cli.tui import ChatTUI
from picho.runner import Runner

config = CLIConfig(
    log={"console_output": False},
)

runner = Runner(config_type="json", config=".picho/config.json")
session_id = runner.create_session()

chat_tui = ChatTUI(runner, session_id, config, confirmation_manager)
await chat_tui.run()
```

## Confirmation System

The confirmation system handles dangerous operations:

```python
from picho.cli.confirmation import ConfirmationManager, ConfirmationRequest

manager = ConfirmationManager()

# Request confirmation
request = ConfirmationRequest(
    title="Execute Command",
    message="This will delete files. Continue?",
    on_approve=lambda: execute_command(),
    on_reject=lambda: cancel(),
)

manager.request(request)
```

## License

MIT

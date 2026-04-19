# Runner Module

Session and agent management for picho.

## Overview

This module provides the Runner class that manages sessions, agents, and event subscriptions.

## Architecture

```
runner/
├── __init__.py      # Module exports
└── runner.py        # Runner implementation
```

## Runner

The Runner class is the main entry point for managing AI sessions:

```python
from picho.runner import Runner, SessionState

# Initialize with config file
runner = Runner(
    config_type="json",
    config="/path/to/config.json",
)

# Or with dict config
runner = Runner(
    config_type="dict",
    config={
        "agent": {"model": "gpt-4o"},
        "session_manager": {"cwd": "/workspace"},
    },
)
```

## Session Management

### Create Session

```python
session_id = runner.create_session()
```

### List Sessions

```python
sessions = runner.list_persisted_sessions(limit=10)
for s in sessions:
    print(f"{s['session_id']}: {s['message_count']} messages")
```

### Load Session

```python
session_id = runner.load_session("/path/to/session.json")
```

### Get Session State

```python
state = runner.get_session(session_id)
if state:
    print(f"Agent: {state.agent}")
    print(f"Session: {state.session}")
```

## Prompting

### Basic Prompt

```python
async for event in runner.prompt(session_id, "Hello!"):
    if event.type == "content_delta":
        print(event.data.delta, end="")
```

### With Steering

Interrupt ongoing conversation:

```python
runner.steer(session_id, "Focus on performance instead")
```

### With Follow-up

Queue message for next turn:

```python
runner.follow_up(session_id, "Can you elaborate?")
```

### Abort

Abort current streaming:

```python
runner.abort(session_id)
```

## Event Subscription

Subscribe to session events:

```python
def on_event(event):
    if event.type == "content_delta":
        print(event.data.delta)
    elif event.type == "tool_execution_start":
        print(f"Tool: {event.tool_name}")

unsubscribe = runner.subscribe(session_id, on_event)

# Later...
unsubscribe()
```

## Event Types

| Event | Description |
|-------|-------------|
| `thinking_delta` | Reasoning content chunk |
| `content_delta` | Text content chunk |
| `message_end` | Complete message |
| `tool_execution_start` | Tool execution begins |
| `tool_execution_end` | Tool execution ends |
| `turn_end` | Turn completed |

## Configuration

```json
{
    "agent": {
        "model": "gpt-4o",
        "instructions": "You are a helpful assistant.",
        "builtin": {
            "skill": ["code-review", "debug"]
        },
        "skill_paths": ["/path/to/skills"]
    },
    "session_manager": {
        "cwd": "/path/to/workspace",
        "persist_dir": "/path/to/sessions"
    }
}
```

## Usage Examples

### Complete Example

```python
import asyncio
from picho.runner import Runner


async def main():
    runner = Runner(
        config_type="json",
        config="~/.picho/config.json",
    )

    session_id = runner.create_session()

    def on_event(event):
        if event.type == "content_delta":
            print(event.data.delta, end="", flush=True)

    runner.subscribe(session_id, on_event)

    await runner.prompt(session_id, "What is Python?")

    runner.save_session(session_id)


asyncio.run(main())
```

### With TUI

```python
from picho.runner import Runner
from picho.cli.chat import ChatTUI

runner = Runner(config_type="json", config="config.json")
session_id = runner.create_session()

tui = ChatTUI(runner, session_id, config)
await tui.run()
```

## License

MIT

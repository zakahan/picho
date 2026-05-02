# Session Module

Session persistence and context compaction for picho.

## Overview

This module provides session management with persistence support and automatic context compaction for long conversations.

## Architecture

```
session/
├── __init__.py          # Module exports
├── types.py             # Type definitions
├── manager.py           # Session manager
├── raw.py               # Raw provider payload debug logs
└── compaction.py        # Context compaction
```

## Session Manager

The SessionManager handles session persistence:

```python
from picho.session import SessionManager

manager = SessionManager(
    cwd="/path/to/sessions",
    persist=True,
)

# Create new session
session = manager.create()

# Add entries
from picho.session import SessionMessageEntry

entry = SessionMessageEntry(message=user_message)
manager.add_entry(session, entry)

# Save session
manager.save(session)

# Load session
session = manager.load("/path/to/session.json")

# List sessions
sessions = manager.list_sessions()
```

## Raw Session Debug Logs

Normal session files store picho's internal message objects. To inspect the final
provider request payload that is actually sent to the model, enable:

```json
{
  "debug": {
    "raw_session": true
  }
}
```

Raw session snapshots are written next to the normal session directory, with
matching session ids:

```text
<base>/sessions/session_abc123.jsonl
<base>/raw_session/session_abc123.json
```

The file is overwritten on each model request, so it always shows the latest
provider payload snapshot. Headers and API keys are not recorded.

## Session Types

### SessionHeader

Metadata for a session:

```python
from picho.session import SessionHeader

header = SessionHeader(
    id="session_abc123",
    created_at=1234567890,
    updated_at=1234567890,
    message_count=10,
)
```

### SessionEntry

Base class for session entries:

```python
from picho.session import (
    SessionEntry,
    SessionMessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
    CompactionEntry,
    BranchSummaryEntry,
)

# Message entry
msg_entry = SessionMessageEntry(message=user_message)

# Model change entry
model_entry = ModelChangeEntry(
    old_model="gpt-3.5",
    new_model="gpt-4o",
)

# Thinking level change
thinking_entry = ThinkingLevelChangeEntry(
    old_level="auto",
    new_level="high",
)

# Compaction entry
compaction_entry = CompactionEntry(
    summary="Previous conversation summary...",
    tokens_before=10000,
    tokens_after=2000,
)
```

## Context Compaction

Automatic context compaction for long conversations:

```python
from picho.session import (
    CompactionSettings,
    should_compact,
    prepare_compaction,
    generate_summary,
)

settings = CompactionSettings(
    max_tokens=128000,
    target_tokens=64000,
    min_messages=10,
)

# Check if compaction needed
if should_compact(session, settings):
    # Prepare compaction
    preparation = prepare_compaction(session, settings)

    # Generate summary
    summary = await generate_summary(preparation.messages, model)

    # Apply compaction
    manager.apply_compaction(session, summary)
```

## Compaction Settings

```python
from picho.session import CompactionSettings

settings = CompactionSettings(
    max_tokens=128000,  # Max context tokens
    target_tokens=64000,  # Target after compaction
    min_messages=10,  # Min messages before compaction
    keep_recent=5,  # Keep recent messages
)
```

## Token Estimation

```python
from picho.session import (
    estimate_tokens,
    calculate_total_tokens,
    estimate_context_tokens,
)

# Estimate tokens for a message
tokens = estimate_tokens(message)

# Calculate total tokens for session
total = calculate_total_tokens(session)

# Estimate context tokens
context_tokens = estimate_context_tokens(context)
```

## Session Persistence

Sessions are saved as JSON files:

```json
{
    "version": 1,
    "header": {
        "id": "session_abc123",
        "created_at": 1234567890,
        "updated_at": 1234567890,
        "message_count": 10
    },
    "entries": [
        {
            "type": "message",
            "timestamp": 1234567890,
            "message": {...}
        }
    ]
}
```

## Usage Examples

### Basic Usage

```python
from picho.session import SessionManager

manager = SessionManager(cwd="/workspace/.picho/sessions")
session = manager.create()

# Add message
manager.add_message(session, user_message)
manager.add_message(session, assistant_message)

# Save
manager.save(session)
```

### With Compaction

```python
from picho.session import SessionManager, CompactionSettings

settings = CompactionSettings(max_tokens=128000)
manager = SessionManager(cwd="/workspace/.picho/sessions", compaction_settings=settings)

session = manager.create()

# Auto-compaction happens when threshold is reached
for msg in messages:
    manager.add_message(session, msg)
    if should_compact(session, settings):
        await manager.compact(session, model)
```

## License

MIT

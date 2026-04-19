# Agent Module

Core agent implementation for picho.

## Overview

This module provides the high-level Agent class that wraps the agent loop with state management, event streaming, and callback support.
The agent loop in this module references pi-mono's working implementation.

## Architecture

```
agent/
├── __init__.py      # Module exports
├── agent.py         # Agent class implementation
├── loop.py          # Agent loop and event stream
└── types.py         # Type definitions
```

## Components

### Agent

The main class for interacting with AI models:

```python
from picho.agent import Agent
from picho.provider.model import get_model

model = get_model(
    provider_type="openai-completion",
    model_name="gpt-4o",
    api_key="your-api-key",
)

agent = Agent(
    model=model,
    instructions="You are a helpful assistant.",
    tools=[...],
)

# Stream responses
async for event in agent.prompt("Hello!"):
    print(event)
```

### AgentLoop

The core event loop that processes model responses:

```python
from picho.agent import agent_loop, AgentEventStream

stream = await agent_loop(
    model=model,
    context=context,
    tools=tools,
)

async for event in stream:
    if event.type == "content_delta":
        print(event.data.delta)
```

### AgentState

State container for agent configuration:

```python
from picho.agent import AgentState

state = AgentState(
    model=model,
    instructions="...",
    tools=[...],
    messages=[...],
    thinking_level="auto",
)
```

## Event Types

| Event | Description |
|-------|-------------|
| `message_start` | Generation begins |
| `content_delta` | Text content chunk |
| `thinking_delta` | Reasoning content chunk |
| `tool_call_start` | Tool call begins |
| `tool_call_delta` | Tool arguments chunk |
| `tool_execution_start` | Tool execution begins |
| `tool_execution_end` | Tool execution ends |
| `message_end` | Complete message |
| `turn_end` | Turn completed |

## Features

- **Streaming**: Real-time response streaming via SSE
- **Tool Calling**: Support for function calling
- **Thinking/Reasoning**: Parse and display reasoning content
- **Callbacks**: Hook into various stages of execution
- **Steering**: Interrupt and redirect ongoing conversations
- **Follow-up**: Queue messages for next turn

## Usage Examples

### Basic Usage

```python
from picho.agent import Agent

agent = Agent(
    model=model,
    instructions="You are a helpful assistant.",
)

async for event in agent.prompt("What is Python?"):
    if event.type == "content_delta":
        print(event.data.delta, end="", flush=True)
```

### With Tools

```python
from picho.tool import Tool, ToolParameter

weather_tool = Tool(
    name="get_weather",
    description="Get weather for a city",
    parameters=ToolParameter(
        type="object",
        properties={"city": {"type": "string"}},
        required=["city"],
    ),
    execute=weather_execute,
)

agent = Agent(
    model=model,
    tools=[weather_tool],
)
```

### With Callbacks

```python
agent = Agent(
    model=model,
    callbacks={
        "on_tool_call": lambda ctx: print(f"Calling {ctx.tool_name}"),
        "on_message": lambda ctx: print(f"Message: {ctx.message}"),
    },
)
```

### Steering

```python
# Interrupt ongoing conversation
agent.steer("Actually, focus on performance instead")

# Queue follow-up for next turn
agent.follow_up("Can you elaborate on that?")
```

## License

MIT

# Provider Module

LLM provider implementations and type definitions for picho.

## Overview

This module provides:

- Abstract `Model` base class
- Model factory for provider management
- OpenAI, Anthropic, Google, and Ark provider implementations
- Type definitions for messages and content

## Architecture

```
provider/
├── __init__.py              # Module exports
├── types.py                 # Type definitions
├── stream.py                # Event stream utilities
├── model/
│   ├── __init__.py          # Model exports
│   ├── base.py              # Base Model class
│   ├── factory.py           # Model factory
│   ├── anthropic.py         # Anthropic Messages API
│   ├── google.py            # Google Gemini API
│   ├── openai_completion.py # OpenAI Chat Completions API
│   ├── openai_responses.py  # OpenAI Responses API
│   └── ark_responses.py     # Ark Responses API
```

## Model Factory

Get a model instance using the factory:

```python
from picho.provider import get_model

model = get_model(
    model_provider="openai-completion",
    model_name="gpt-4o",
    api_key="your-api-key",
    base_url="https://api.openai.com/v1",  # Optional
)
```

## Type Definitions

### Messages

```python
from picho.provider.types import (
    Message,
    UserMessage,
    AssistantMessage,
    Context,
)

# User message
user_msg = UserMessage(content="Hello!")

# Assistant message
assistant_msg = AssistantMessage(
    content=[TextContent(type="text", text="Hi there!")]
)

# Context
context = Context(
    instructions="You are a helpful assistant.",
    messages=[user_msg],
    tools=[...],
)
```

### Content Types

```python
from picho.provider.types import (
    TextContent,
    ImageBase64Content,
    ImageUrlContent,
    ImageFileIdContent,
    ThinkingContent,
    ToolCall,
)

# Text content
text = TextContent(type="text", text="Hello")

# Image content (base64)
image_base64 = ImageBase64Content(
    type="image_base64",
    data="base64_encoded_data",
    mime_type="image/png",
)

# Image content (URL)
image_url = ImageUrlContent(
    type="image_url",
    url="https://example.com/image.png",
)

# Image content (file_id, Ark only)
image_file_id = ImageFileIdContent(
    type="image_file_id",
    file_id="file-abc123",
)

# Thinking content
thinking = ThinkingContent(type="thinking", thinking="Let me think...")

# Tool call
tool_call = ToolCall(
    type="toolCall",
    id="call_123",
    name="get_weather",
    arguments={"city": "Beijing"},
)
```

## Provider Implementations

### OpenAI Completions

```python
from picho.provider import get_model

model = get_model(
    model_provider="openai-completion",
    model_name="gpt-4o",
    api_key="your-api-key",
)

stream = await model.stream(context)

async for event in stream:
    if event.type == "content_delta":
        print(event.data.delta, end="")
```

### OpenAI Responses

```python
model = get_model(
    model_provider="openai-responses",
    model_name="gpt-4o",
    api_key="your-api-key",
)
```

### Anthropic Messages

```python
model = get_model(
    model_provider="anthropic",
    model_name="claude-sonnet-4-5",
    api_key="your-api-key",
)
```

### Google Gemini

```python
model = get_model(
    model_provider="google",
    model_name="gemini-3-flash-preview",
    api_key="your-api-key",
)
```

If you install `picho` from PyPI and want to use the Google Gemini provider, install the optional dependency:

```bash
uv add picho["provider-google"]
```

### Ark Responses

```python
model = get_model(
    model_provider="ark-responses",
    model_name="doubao-seed-2-0-lite-260215",
    api_key="your-api-key",
)
```

### Custom Base URL

```python
model = get_model(
    model_provider="openai-completion",
    model_name="custom-model",
    api_key="your-api-key",
    base_url="https://your-api-endpoint.com/v1",
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
| `message_end` | Complete message |

## Creating Custom Providers

### 1. Implement the Model Class

```python
from picho.provider.model.base import Model
from picho.provider.stream import EventStream, StreamEvent


class MyCustomModel(Model):
    def __init__(self, model_name: str, api_key: str, **kwargs):
        super().__init__(model_name=model_name, model_provider="my-provider")
        self.api_key = api_key

    async def stream(self, context, options=None):
        stream = EventStream(
            is_terminal=lambda e: e.type == "message_end",
            extract_result=lambda e: e.data,
        )

        async def run():
            # Call your API
            stream.push(StreamEvent(type="content_delta", data=...))
            stream.push(StreamEvent(type="message_end", data=message))

        asyncio.create_task(run())
        return stream
```

### 2. Register the Provider

```python
from picho.provider.model.factory import register_model


@register_model("my-provider")
class MyCustomModel(Model):
# ... implementation
```

## License

MIT

# Provider 模块

picho 的 LLM 提供商实现和类型定义。

## 概述

本模块提供：

- 抽象 `Model` 基类
- 模型工厂用于提供商管理
- OpenAI、Anthropic、Google 与 Ark 提供商实现
- 消息和内容的类型定义

## 架构

```
provider/
├── __init__.py              # 模块导出
├── types.py                 # 类型定义
├── stream.py                # 事件流工具
├── model/
│   ├── __init__.py          # 模型导出
│   ├── base.py              # 基础 Model 类
│   ├── factory.py           # 模型工厂
│   ├── anthropic.py         # Anthropic Messages API
│   ├── google.py            # Google Gemini API
│   ├── openai_completion.py # OpenAI Chat Completions API
│   ├── openai_responses.py  # OpenAI Responses API
│   └── ark_responses.py     # Ark Responses API
```

## 模型工厂

使用工厂获取模型实例：

```python
from picho.provider import get_model

model = get_model(
    model_provider="openai-completion",
    model_name="gpt-4o",
    api_key="your-api-key",
    base_url="https://api.openai.com/v1",  # 可选
)
```

## 类型定义

### 消息

```python
from picho.provider.types import (
    Message,
    UserMessage,
    AssistantMessage,
    Context,
)

# 用户消息
user_msg = UserMessage(content="Hello!")

# 助手消息
assistant_msg = AssistantMessage(
    content=[TextContent(type="text", text="Hi there!")]
)

# 上下文
context = Context(
    instructions="You are a helpful assistant.",
    messages=[user_msg],
    tools=[...],
)
```

### 内容类型

```python
from picho.provider.types import (
    TextContent,
    ImageBase64Content,
    ImageUrlContent,
    ImageFileIdContent,
    ThinkingContent,
    ToolCall,
)

# 文本内容
text = TextContent(type="text", text="Hello")

# 图片内容 (base64)
image_base64 = ImageBase64Content(
    type="image_base64",
    data="base64_encoded_data",
    mime_type="image/png",
)

# 图片内容 (URL)
image_url = ImageUrlContent(
    type="image_url",
    url="https://example.com/image.png",
)

# 图片内容 (file_id, 仅 Ark 支持)
image_file_id = ImageFileIdContent(
    type="image_file_id",
    file_id="file-abc123",
)

# 思考内容
thinking = ThinkingContent(type="thinking", thinking="Let me think...")

# 工具调用
tool_call = ToolCall(
    type="toolCall",
    id="call_123",
    name="get_weather",
    arguments={"city": "Beijing"},
)
```

## 提供商实现

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

如果你是从 PyPI 安装 `picho`，并且需要使用 Google Gemini provider，请额外安装可选依赖：

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

### 自定义 Base URL

```python
model = get_model(
    model_provider="openai-completion",
    model_name="custom-model",
    api_key="your-api-key",
    base_url="https://your-api-endpoint.com/v1",
)
```

## 事件类型

| 事件 | 描述 |
|------|------|
| `message_start` | 生成开始 |
| `content_delta` | 文本内容块 |
| `thinking_delta` | 推理内容块 |
| `tool_call_start` | 工具调用开始 |
| `tool_call_delta` | 工具参数块 |
| `message_end` | 完整消息 |

## 创建自定义提供商

### 1. 实现 Model 类

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
            # 调用你的 API
            stream.push(StreamEvent(type="content_delta", data=...))
            stream.push(StreamEvent(type="message_end", data=message))

        asyncio.create_task(run())
        return stream
```

### 2. 注册提供商

```python
from picho.provider.model.factory import register_model


@register_model("my-provider")
class MyCustomModel(Model):
# ... 实现
```

## 许可证

MIT

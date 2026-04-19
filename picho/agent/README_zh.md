# Agent 模块

picho 的核心 Agent 实现。

## 概述

本模块提供高层 Agent 类，封装了 agent 循环、状态管理、事件流和回调支持。
本模块中的 agent loop 核心实现参考了 `pi-mono` 的工作实现。

## 架构

```
agent/
├── __init__.py      # 模块导出
├── agent.py         # Agent 类实现
├── loop.py          # Agent 循环和事件流
└── types.py         # 类型定义
```

## 组件

### Agent

与 AI 模型交互的主类：

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

# 流式响应
async for event in agent.prompt("Hello!"):
    print(event)
```

### AgentLoop

处理模型响应的核心事件循环：

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

Agent 配置的状态容器：

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

## 事件类型

| 事件 | 描述 |
|------|------|
| `message_start` | 生成开始 |
| `content_delta` | 文本内容块 |
| `thinking_delta` | 推理内容块 |
| `tool_call_start` | 工具调用开始 |
| `tool_call_delta` | 工具参数块 |
| `tool_execution_start` | 工具执行开始 |
| `tool_execution_end` | 工具执行结束 |
| `message_end` | 完整消息 |
| `turn_end` | 回合结束 |

## 功能特性

- **流式响应**：通过 SSE 实现实时响应流
- **工具调用**：支持函数调用
- **思考/推理**：解析和显示推理内容
- **回调**：在执行各阶段插入钩子
- **引导**：中断并重定向正在进行的对话
- **后续消息**：为下一回合排队消息

## 使用示例

### 基本使用

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

### 使用工具

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

### 使用回调

```python
agent = Agent(
    model=model,
    callbacks={
        "on_tool_call": lambda ctx: print(f"Calling {ctx.tool_name}"),
        "on_message": lambda ctx: print(f"Message: {ctx.message}"),
    },
)
```

### 引导

```python
# 中断正在进行的对话
agent.steer("Actually, focus on performance instead")

# 为下一回合排队后续消息
agent.follow_up("Can you elaborate on that?")
```

## 许可证

MIT

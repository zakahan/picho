# Runner 模块

picho 的会话和 Agent 管理。

## 概述

本模块提供 Runner 类，用于管理会话、Agent 和事件订阅。

## 架构

```
runner/
├── __init__.py      # 模块导出
└── runner.py        # Runner 实现
```

## Runner

Runner 类是管理 AI 会话的主要入口点：

```python
from picho.runner import Runner, SessionState

# 使用配置文件初始化
runner = Runner(
    config_type="json",
    config="/path/to/config.json",
)

# 或使用字典配置
runner = Runner(
    config_type="dict",
    config={
        "agent": {"model": "gpt-4o"},
        "session_manager": {"cwd": "/workspace"},
    },
)
```

## 会话管理

### 创建会话

```python
session_id = runner.create_session()
```

### 列出会话

```python
sessions = runner.list_persisted_sessions(limit=10)
for s in sessions:
    print(f"{s['session_id']}: {s['message_count']} messages")
```

### 加载会话

```python
session_id = runner.load_session("/path/to/session.json")
```

### 获取会话状态

```python
state = runner.get_session(session_id)
if state:
    print(f"Agent: {state.agent}")
    print(f"Session: {state.session}")
```

## 提示

### 基本提示

```python
async for event in runner.prompt(session_id, "Hello!"):
    if event.type == "content_delta":
        print(event.data.delta, end="")
```

### 引导

中断正在进行的对话：

```python
runner.steer(session_id, "Focus on performance instead")
```

### 后续消息

为下一回合排队消息：

```python
runner.follow_up(session_id, "Can you elaborate?")
```

### 中止

中止当前流式响应：

```python
runner.abort(session_id)
```

## 事件订阅

订阅会话事件：

```python
def on_event(event):
    if event.type == "content_delta":
        print(event.data.delta)
    elif event.type == "tool_execution_start":
        print(f"Tool: {event.tool_name}")

unsubscribe = runner.subscribe(session_id, on_event)

# 稍后...
unsubscribe()
```

## 事件类型

| 事件 | 描述 |
|------|------|
| `thinking_delta` | 推理内容块 |
| `content_delta` | 文本内容块 |
| `message_end` | 完整消息 |
| `tool_execution_start` | 工具执行开始 |
| `tool_execution_end` | 工具执行结束 |
| `turn_end` | 回合结束 |

## 配置

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

## 使用示例

### 完整示例

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

### 使用 TUI

```python
from picho.runner import Runner
from picho.cli.chat import ChatTUI

runner = Runner(config_type="json", config="config.json")
session_id = runner.create_session()

tui = ChatTUI(runner, session_id, config)
await tui.run()
```

## 许可证

MIT

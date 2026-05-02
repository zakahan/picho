# Session 模块

picho 的会话持久化和上下文压缩。

## 概述

本模块提供会话管理，支持持久化和长对话的自动上下文压缩。

## 架构

```
session/
├── __init__.py          # 模块导出
├── types.py             # 类型定义
├── manager.py           # 会话管理器
├── raw.py               # provider 原始 payload 调试日志
└── compaction.py        # 上下文压缩
```

## 会话管理器

SessionManager 处理会话持久化：

```python
from picho.session import SessionManager

manager = SessionManager(
    cwd="/path/to/sessions",
    persist=True,
)

# 创建新会话
session = manager.create()

# 添加条目
from picho.session import SessionMessageEntry

entry = SessionMessageEntry(message=user_message)
manager.add_entry(session, entry)

# 保存会话
manager.save(session)

# 加载会话
session = manager.load("/path/to/session.json")

# 列出会话
sessions = manager.list_sessions()
```

## Raw Session 调试日志

普通 session 文件记录的是 picho 内部消息对象。如果需要查看最终实际发送给
模型 provider 的 request payload，可以开启：

```json
{
  "debug": {
    "raw_session": true
  }
}
```

Raw session 快照文件会写在普通 session 目录旁边，并复用相同 session id：

```text
<base>/sessions/session_abc123.jsonl
<base>/raw_session/session_abc123.json
```

每次模型请求都会覆盖写这个文件，因此它始终展示最新一次 provider payload 快照。
Raw session 只记录 provider payload 和基础元信息，不记录 headers 或 API key。

## 会话类型

### SessionHeader

会话元数据：

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

会话条目的基类：

```python
from picho.session import (
    SessionEntry,
    SessionMessageEntry,
    ModelChangeEntry,
    ThinkingLevelChangeEntry,
    CompactionEntry,
    BranchSummaryEntry,
)

# 消息条目
msg_entry = SessionMessageEntry(message=user_message)

# 模型变更条目
model_entry = ModelChangeEntry(
    old_model="gpt-3.5",
    new_model="gpt-4o",
)

# 思考级别变更
thinking_entry = ThinkingLevelChangeEntry(
    old_level="auto",
    new_level="high",
)

# 压缩条目
compaction_entry = CompactionEntry(
    summary="Previous conversation summary...",
    tokens_before=10000,
    tokens_after=2000,
)
```

## 上下文压缩

长对话的自动上下文压缩：

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

# 检查是否需要压缩
if should_compact(session, settings):
    # 准备压缩
    preparation = prepare_compaction(session, settings)

    # 生成摘要
    summary = await generate_summary(preparation.messages, model)

    # 应用压缩
    manager.apply_compaction(session, summary)
```

## 压缩设置

```python
from picho.session import CompactionSettings

settings = CompactionSettings(
    max_tokens=128000,  # 最大上下文 token 数
    target_tokens=64000,  # 压缩后目标 token 数
    min_messages=10,  # 压缩前最小消息数
    keep_recent=5,  # 保留最近的消息数
)
```

## Token 估算

```python
from picho.session import (
    estimate_tokens,
    calculate_total_tokens,
    estimate_context_tokens,
)

# 估算消息的 token 数
tokens = estimate_tokens(message)

# 计算会话总 token 数
total = calculate_total_tokens(session)

# 估算上下文 token 数
context_tokens = estimate_context_tokens(context)
```

## 会话持久化

会话保存为 JSON 文件：

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

## 使用示例

### 基本使用

```python
from picho.session import SessionManager

manager = SessionManager(cwd="/workspace/.picho/sessions")
session = manager.create()

# 添加消息
manager.add_message(session, user_message)
manager.add_message(session, assistant_message)

# 保存
manager.save(session)
```

### 使用压缩

```python
from picho.session import SessionManager, CompactionSettings

settings = CompactionSettings(max_tokens=128000)
manager = SessionManager(cwd="/workspace/.picho/sessions", compaction_settings=settings)

session = manager.create()

# 当达到阈值时自动压缩
for msg in messages:
    manager.add_message(session, msg)
    if should_compact(session, settings):
        await manager.compact(session, model)
```

## 许可证

MIT

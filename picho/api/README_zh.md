# picho API Server

picho API Server 是基于 FastAPI 的 Web 服务器，通过 REST API 端点暴露 Agent 能力，支持会话管理和流式对话功能。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        产品服务层                                │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ 自定义路由       │  │ 自定义适配器     │  │ 自定义模型       │ │
│  │ /projects       │  │ SandboxSession  │  │ ProjectRequest  │ │
│  │ /tasks          │  │ APIAdapter      │  │ AssetRequest    │ │
│  │ /assets         │  │                 │  │                 │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│           │                   │                   │             │
└───────────┼───────────────────┼───────────────────┼─────────────┘
            │                   │                   │
            ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      APIAppBuilder                              │
│                     (组装助手)                                   │
├─────────────────────────────────────────────────────────────────┤
│  .add_bundle(CoreRoutesBundle)                                  │
│  .add_bundle(SessionRouteBundle)                                │
│  .build() → FastAPI App                                         │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      路由包 (Route Bundles)                      │
├──────────────────────────┬──────────────────────────────────────┤
│   CoreRoutesBundle       │      SessionRouteBundle              │
│   ─────────────────      │      ──────────────────              │
│   GET /health            │      POST /sessions                  │
│                          │      GET /sessions/{id}              │
│                          │      GET /sessions                   │
│                          │      DELETE /sessions/{id}           │
│                          │      POST /run_sse                   │
└──────────────────────────┴──────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SessionAPIAdapter                            │
│                     (扩展点)                                     │
├─────────────────────────────────────────────────────────────────┤
│  生命周期钩子:                                                   │
│  • validate_run_request() - 执行前请求校验                       │
│  • on_run_start() - 初始化运行状态                               │
│  • convert_message() - 转换请求消息为内部 Message                │
│  • serialize_event() - 格式化 SSE 事件                          │
│  • on_run_complete() - 处理成功完成                             │
│  • on_run_error() - 处理错误                                    │
│  • on_run_cancelled() - 处理取消                                │
└─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Runner                                  │
│                    (Agent 执行引擎)                              │
└─────────────────────────────────────────────────────────────────┘
```

## 核心概念

### 组合优于继承

API 层采用组合式架构。产品服务通过组合可复用的构建块来构建 API，而不是继承一个庞大的服务器类：

- **路由包 (Route Bundles)**: 可复用的 API 端点集合
- **适配器 (Adapters)**: 可定制的行为钩子，用于请求处理
- **构建器 (Builder)**: 用于组装 FastAPI 应用的助手

### 核心组件

#### `APIAppBuilder`

流式构建器，用于组装 FastAPI 应用：

```python
from picho.api.composition import APIAppBuilder, CoreRoutesBundle, SessionRouteBundle
from picho.api.schemas import CreateSessionRequest, RequestMessage, RunRequest

app = (APIAppBuilder(title="My Agent API")
       .add_bundle(CoreRoutesBundle())
       .add_bundle(SessionRouteBundle(
    runner=runner,
    adapter=adapter,
    create_session_request_model=CreateSessionRequest,
    request_message_model=RequestMessage,
    run_request_model=RunRequest,
))
       .build())
```

#### `CoreRoutesBundle`

提供最通用的基础路由：

- `GET /health` - 健康检查端点

#### `SessionRouteBundle`

提供可复用的会话和 SSE 端点：

- `POST /sessions` - 创建新会话
- `GET /sessions/{session_id}` - 根据 ID 获取会话
- `GET /sessions` - 列出所有会话
- `DELETE /sessions/{session_id}` - 删除会话
- `POST /sessions/{session_id}/abort` - 中止当前会话中的运行
- `POST /sessions/{session_id}/steer` - 为会话追加 steering 消息
- `POST /run_sse` - 执行 Agent（SSE 流式）

#### `SessionAPIAdapter`

定制行为的主要扩展点：

| 方法 | 用途 |
|------|------|
| `validate_run_request()` | 执行前验证请求 |
| `on_run_start()` | Agent 执行前初始化状态 |
| `convert_message()` | 将请求消息转换为内部 `Message` 格式 |
| `serialize_event()` | 格式化 Agent 事件为 SSE 输出 |
| `on_run_complete()` | 处理执行成功完成 |
| `on_run_error()` | 处理执行错误 |
| `on_run_cancelled()` | 处理执行取消 |

### 请求流转

```
HTTP 请求
    │
    ▼
SessionRouteBundle
    │
    ▼
SessionAPIAdapter.validate_run_request()
    │
    ▼
SessionAPIAdapter.on_run_start()
    │
    ▼
SessionAPIAdapter.convert_message()
    │
    ▼
Runner.prompt()
    │
    ▼
SSE 事件循环
    │
    ▼
SessionAPIAdapter.serialize_event()
    │
    ▼
SessionAPIAdapter.on_run_complete() / on_run_error()
    │
    ▼
HTTP SSE 响应
```

## 使用方式

### 默认服务器（简单场景）

对于基础用例，直接使用默认的 `APIServer`：

```python
import os

from picho.api.server import APIServer
from picho.runner import Runner

config_path = os.path.join(os.getcwd(), ".picho", "config.json")

runner = Runner(config_type="json", config=config_path)
server = APIServer(runner, host="0.0.0.0", port=8000)
server.run()
```

### 自定义适配器（产品服务）

对于需要定制行为的产品服务：

```python
from picho.api.composition import (
    APIAppBuilder,
    CoreRoutesBundle,
    SessionRouteBundle,
    SessionAPIAdapter
)
from picho.api.schemas import CreateSessionRequest, RequestMessage, RunRequest
from picho.provider.types import UserMessage, TextContent


class MySessionAPIAdapter(SessionAPIAdapter):
    async def validate_run_request(self, req):
        # 自定义校验逻辑
        pass

    async def on_run_start(self, req):
        # 自定义初始化
        return run_state, initial_messages

    async def convert_message(self, req_message, req=None):
        # 自定义消息转换
        return UserMessage(content=[TextContent(type="text", text=req_message.content)])


# 构建应用
app = (APIAppBuilder(title="My Product API")
       .add_bundle(CoreRoutesBundle())
       .add_bundle(SessionRouteBundle(
    runner=my_runner,
    adapter=MySessionAPIAdapter(),
    create_session_request_model=MyCreateSessionRequest,
    request_message_model=RequestMessage,
    run_request_model=MyRunRequest
))
       .build())


# 添加自定义路由
@app.post("/custom")
async def custom_endpoint():
    pass
```

## 设计原则

1. **框架提供构建块** - 可复用的路由包和适配器
2. **产品组合扩展** - 按需组装，按需定制
3. **避免深层继承** - 组合优于继承，更灵活
4. **清晰分离** - 框架逻辑与产品逻辑分离

## 核心特性

- **极简设计**: 只需要 `session_id`
- **SSE 流式响应**: 通过 `/run_sse` 端点接收实时事件流
- **多模态支持**: 支持文本、图片等多种输入类型
- **生产就绪**: 内置错误处理，无需复杂配置

## 快速开始

### 安装

```bash
uv sync
```

### 基础用法

```python
import os
from picho.runner import Runner
from picho.api.server import APIServer

config_path = os.path.join(os.getcwd(), ".picho", "config.json")
runner = Runner(config_type="json", config=config_path)

server = APIServer(runner)
server.run()
```

### API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/sessions` | POST | 创建会话 |
| `/sessions/{id}` | GET | 获取会话 |
| `/sessions` | GET | 列出会话 |
| `/sessions/{id}` | DELETE | 删除会话 |
| `/sessions/{id}/abort` | POST | 中止当前运行 |
| `/sessions/{id}/steer` | POST | 追加 steering 消息 |
| `/run_sse` | POST | 执行 Agent（SSE 流式） |

### 示例：发送消息

```python
import httpx

# 创建会话
response = httpx.post("http://localhost:8000/sessions")
session_id = response.json()["session_id"]

# 通过 SSE 发送消息
with httpx.stream("POST", "http://localhost:8000/run_sse", json={
    "session_id": session_id,
    "message": {"role": "user", "content": "你好！"}
}) as response:
    for line in response.iter_lines():
        if line.startswith("data: "):
            print(line[6:])
```

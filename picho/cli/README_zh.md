# CLI 模块

picho 的命令行接口。

## 概述

本模块提供与 picho 交互的命令行接口，包括交互式编程 TUI。

## 架构

```
cli/
├── __init__.py              # 模块导出
├── main.py                  # CLI 入口点
├── chat.py                  # Chat 命令实现
├── init.py                  # Init 命令实现
├── tui.py                   # Hermes 风格 chat TUI（prompt_toolkit + rich）
├── config.py                # CLI 配置
├── confirmation.py          # 确认管理
└── security_callback.py     # 安全回调处理器
```

## 命令

### picho init

初始化项目配置文件：

```bash
picho init [OPTIONS]
```

选项：
- `-p, --provider` - LLM 提供商 (openai-completion, openai-responses, ark-responses)
- `-m, --model` - 模型名称
- `--base-url` - API 基础 URL
- `-y, --yes` - 使用默认值，不提示
- `--path` - 目标目录（默认：当前目录）
- `--auto` - 使用 ~/.picho 全局配置作为模板

示例：
```bash
# 交互模式
picho init

# 快速初始化 OpenAI
picho init -p openai-completion -y

# 指定提供商和模型
picho init -p ark-responses -m doubao-pro-32k

# 在指定目录初始化
picho init --path /path/to/project

# 使用全局配置作为模板
picho init --auto
```

### picho chat

启动交互式编程会话：

```bash
picho chat [OPTIONS]
```

选项：
- `-c, --config` - 配置 JSON 文件路径
- `-r, --runner` - Python 模块路径，模块需导出 `runner` 变量
- `-v, --verbose` - 启用详细日志

示例：
```bash
# 使用默认配置 (.picho/config.json)
picho chat

# 指定配置文件
picho chat -c /path/to/config.json

# 从 Python 模块加载动态 Runner
picho chat -r my_runner.py
```

#### 动态 Runner 模块

你可以创建一个 Python 模块来动态构建 Runner：

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
        "instructions": "你是一个有用的助手。",
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

然后运行：
```bash
picho chat -r my_runner.py
```

### 交互命令

在 chat TUI 内：

| 命令 | 描述 |
|------|------|
| `/help` | 显示可用命令 |
| `/quit`, `/q` | 退出会话 |
| `/abort` | 中止当前流式响应 |
| `/new` | 创建新会话 |
| `/sessions [n]` | 列出最近的会话 |
| `/checkout <id>` | 切换到指定会话 |
| `/agent` | 显示 Agent 信息 |

### 键盘快捷键

| 按键 | 操作 |
|------|------|
| `Enter` | 发送消息 |
| `Ctrl+C` | 中止流式响应 |
| `Ctrl+D` | 退出 |
| `上/下` | 滚动聊天 |
| `Page Up/Down` | 按页滚动 |
| `Home/End` | 滚动到顶部/底部 |

## 配置

配置存储在 `.picho/config.json`：

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

`load_cli_config()` 会按以下顺序查找 TUI 配置：

- 当前目录下的 `.picho/tui.json`
- 用户目录下的 `~/.picho/tui.json`

如果这两处都不存在，则会在当前目录自动创建默认的 `.picho/tui.json`。

## TUI 功能

TUI 基于 `prompt_toolkit`（底部固定的输入框 + 状态栏）和 `rich`
（启动 banner / 面板）构建，采用 Hermes 风格的金/铜配色，按行流式输出 ANSI。
提供：

- **底部固定输入框**：输入框始终钉在底部，上方为滚动对话
- **实时状态栏**：显示模型、session id、workspace，以及 `STREAMING` / `QUEUED` 指示
- **流式输出**：assistant 文本和 thinking 逐字符流式显示
- **工具活动**：`┊ Tool call: ...` / `┊ Tool result: ...` 行内显示
- **确认栏**：危险操作的 y/n 行内批准
- **Steering 与 follow-up**：流式中直接输入即为 steer；以 `>` 开头则入队 follow-up

## 使用示例

### 快速开始

```bash
# 初始化项目
picho init -p openai-completion -y

# 设置 API Key
export OPENAI_API_KEY=your-api-key

# 启动编程会话
picho chat
```

### 编程方式使用

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

## 确认系统

确认系统处理危险操作：

```python
from picho.cli.confirmation import ConfirmationManager, ConfirmationRequest

manager = ConfirmationManager()

# 请求确认
request = ConfirmationRequest(
    title="Execute Command",
    message="This will delete files. Continue?",
    on_approve=lambda: execute_command(),
    on_reject=lambda: cancel(),
)

manager.request(request)
```

## 许可证

MIT

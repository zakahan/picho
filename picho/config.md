# picho 配置说明

## 完整配置示例

```json
{
  "path": {
    "base": "/path/to/workspace",
    "logs": "/path/to/logs",
    "sessions": "/path/to/sessions",
    "executor": "/path/to/executor",
    "skills": [".picho/skills"]
  },
  "agent": {
    "model": {
      "model_provider": "openai | anthropic | ark-responses | ...",
      "model_name": "gpt-4o | claude-sonnet-4 | doubao-seed-2-0-lite-260215",
      "base_url": "https://api.openai.com/v1 | https://ark.cn-beijing.volces.com/api/v3",
      "api_key": "your-api-key",
      "input_types": ["text", "image", "video"]
    },
    "instructions": "你是一个优秀的AI助手，你的名字叫`picho`，你的回答风格是简洁",
    "thinking_level": "auto | enabled | disabled",
    "builtin": {
      "tool": ["read", "write", "bash", "edit"],
      "skill": ["code-review", "debug", "skill-creator"],
      "tool_config": {
        "read": {
          "extensions": [
            ".picho/read_extensions/csv_reader.py",
            "my_project.read_extensions"
          ],
          "video_compression": {
            "enabled": true,
            "trigger_size_mb": 512
          }
        }
      }
    },
    "compaction": {
      "enabled": true,
      "reserve_tokens": 16384,
      "keep_recent_tokens": 20000,
      "trigger_threshold": 100000
    },
    "steering_mode": "one-at-a-time | all",
    "follow_up_mode": "one-at-a-time | all",
    "executor": {
      "env_path": ".env",
      "env": {
        "KEY": "value"
      },
      "init_command": "export PATH=\"/usr/local/bin:$PATH\""
    }
  },
  "session_manager": {
    "persist": true
  }
}
```

## 配置项详解

### path

工作目录配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base` | string | 当前目录 | 工作区根目录 |
| `logs` | string | `base` | 日志文件存放目录 |
| `sessions` | string | `base` | 会话文件存放目录 |
| `executor` | string | `base` | bash 工具执行命令时的 cwd |
| `skills` | string[] | `[".picho/skills"]` | skill 文件搜索路径列表 |

---

### agent

Agent 相关配置。

#### agent.model

模型配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_provider` | string | null | 模型提供商: `openai`, `anthropic`, `ark-responses` 等 |
| `model_name` | string | null | 模型名称，如 `gpt-4o`, `claude-sonnet-4-20250514` |
| `base_url` | string | null | API 端点 URL |
| `api_key` | string | null | API 密钥 |
| `input_types` | string[] | `["text"]` | 支持的输入类型，可选: `text`, `image`, `video`, `audio` |

#### agent.instructions

| 类型 | 默认值 | 说明 |
|------|--------|------|
| string | `"You are a helpful AI assistant named picho."` | 系统提示词 |

#### agent.thinking_level

| 类型 | 默认值 | 说明 |
|------|--------|------|
| `"auto"` \| `"enabled"` \| `"disabled"` | `"auto"` | 是否启用思考模式 |

#### agent.builtin

内置工具和技能配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tool` | string[] | `["read", "write", "bash", "edit"]` | 启用的内置工具 |
| `skill` | string[] | `["code-review", "debug", "skill-creator"]` | 启用的内置技能 |

**可用工具:**
- `read` - 读取文件内容
- `write` - 写入文件内容
- `bash` - 执行 bash 命令
- `edit` - 编辑文件（替换文本）

**可用技能:**
- `code-review` - 代码审查
- `debug` - 调试助手
- `skill-creator` - 创建自定义技能

#### agent.builtin.tool_config.read

`read` 工具专属配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `extensions` | string[] | `[]` | 自定义 read 扩展模块列表，支持 Python 模块名或 `.py` 文件路径 |
| `video_compression.enabled` | boolean | `true` | 超大视频是否自动压缩 |
| `video_compression.trigger_size_mb` | int | `512` | 触发自动压缩的体积阈值 |

`extensions` 规则：
- 每个条目可以是模块名，例如 `my_project.read_extensions`
- 也可以是相对工作区的文件路径，例如 `.picho/read_extensions/csv_reader.py`
- 自定义扩展会优先于内建后缀处理逻辑执行，适合覆盖或新增某类文件读取策略

最小扩展示例：

```python
from pathlib import Path

from picho.builtin.tool.extension.read import ReadExtension, ReadExtensionContext
from picho.provider.types import TextContent
from picho.tool import ToolResult


def read_csv(context: ReadExtensionContext) -> ToolResult:
    content = Path(context.resolved_path).read_text(encoding="utf-8")
    lines = content.splitlines()
    preview = "\n".join(lines[: context.limit or 20])
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=f"[CSV preview]\n{preview}",
            )
        ]
    )


READ_EXTENSIONS = [
    ReadExtension(
        name="csv-reader",
        extensions=[".csv"],
        execute=read_csv,
    )
]
```

#### agent.compaction

上下文压缩配置，用于管理 token 使用。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用上下文压缩 |
| `reserve_tokens` | int | `16384` | 保留的 token 数量（用于压缩后保留的基础上下文） |
| `keep_recent_tokens` | int | `20000` | 保留最近的 token 数量 |
| `trigger_threshold` | int | `100000` | 触发压缩的 token 阈值 |

#### agent.steering_mode

| 类型 | 默认值 | 说明 |
|------|--------|------|
| `"one-at-a-time"` \| `"all"` | `"one-at-a-time"` | 工具调用模式 |

- `one-at-a-time`: 每次只执行一个工具
- `all`: 可同时执行多个工具 |

#### agent.follow_up_mode

| 类型 | 默认值 | 说明 |
|------|--------|------|
| `"one-at-a-time"` \| `"all"` | `"one-at-a-time"` | 后续消息处理模式 |

#### agent.executor

Bash 工具执行器配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `env_path` | string | null | `.env` 文件路径，加载环境变量 |
| `env` | object | `{}` | 直接配置的环境变量键值对 |
| `init_command` | string | null | 每次执行 bash 命令前预先执行的命令 |

**env_path 示例:**
```json
"env_path": ".env"
```
加载 `.env` 文件中的环境变量。

**env 示例:**
```json
"env": {
  "DATABASE_URL": "postgres://localhost/mydb",
  "DEBUG": "true"
}
```

**init_command 示例:**
```json
"init_command": "export PATH=\"/usr/local/bin:$PATH\""
```
每次执行 bash 命令前会先执行此命令。`$PATH` 等变量会使用系统当前值展开。

---

### session_manager

会话管理配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `persist` | boolean | `true` | 是否持久化会话 |

---

## 最小配置示例

```json
{
  "agent": {
    "model": {
      "model_provider": "ark-responses",
      "model_name": "doubao-seed-2-0-lite-260215",
      "base_url": "https://ark.cn-beijing.volces.com/api/v3",
      "api_key": "your-ark-api-key",
      "input_types": ["text", "image", "video"]
    }
  }
}
```

## 环境变量注入示例

### 方式一：使用 .env 文件

```json
{
  "agent": {
    "executor": {
      "env_path": ".env"
    }
  }
}
```

`.env` 文件内容:
```
API_KEY=xxx
DATABASE_URL=postgres://...
```

### 方式二：直接配置环境变量

```json
{
  "agent": {
    "executor": {
      "env": {
        "API_KEY": "xxx",
        "DATABASE_URL": "postgres://..."
      }
    }
  }
}
```

### 方式三：使用 init_command 修改 PATH

```json
{
  "agent": {
    "executor": {
      "init_command": "export PATH=\"/usr/local/bin:$PATH\""
    }
  }
}
```

### 方式四：组合使用

```json
{
  "agent": {
    "executor": {
      "env_path": ".env",
      "env": {
        "OVERRIDE_KEY": "override_value"
      },
      "init_command": "export PATH=\"/usr/local/bin:$PATH\""
    }
  }
}
```

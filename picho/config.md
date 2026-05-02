# picho 配置说明

## 完整配置示例

```json
{
  "path": {
    "base": "~/.picho",
    "logs": "/path/to/logs",
    "sessions": "/path/to/sessions",
    "telemetry": "/path/to/telemetry",
    "cache": "/path/to/caches",
    "executor": "/path/to/workspace",
    "skills": ["skills"]
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

路径配置分成两层：`base` 是 picho 状态根目录，`executor` 是 builtin tools 的工作区。
如果完全不配置 `path`，`base` 默认是当前目录下的 `.picho`，而 `executor` 默认是当前目录本身。
没有显式配置的状态目录会从 `base` 下分发；显式配置的目录按原样使用，不会再自动追加 `.picho` 或固定子目录。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base` | string | `<cwd>/.picho` | picho 状态根目录 |
| `logs` | string | `base/logs` | 日志文件存放目录；显式配置时即最终目录 |
| `sessions` | string | `base/sessions` | 会话文件存放目录；显式配置时即最终目录 |
| `telemetry` | string | `base/telemetry` | telemetry 数据存放目录；显式配置时即最终目录 |
| `cache` | string | `base/caches` | read 转换、压缩、转写等缓存根目录；显式配置时即最终目录 |
| `executor` | string | 当前目录 | builtin tools 的 workspace：`bash` 的 cwd，也是 `read/write/edit` 的文件访问边界 |
| `skills` | string[] | `["skills"]` | skill 文件搜索路径列表；相对路径基于 `base` 解析 |

例如只配置：

```json
{
  "path": {
    "base": "~/.picho"
  }
}
```

会得到 `~/.picho/logs`、`~/.picho/sessions`、`~/.picho/telemetry`、`~/.picho/caches`，但 builtin tools 仍在启动 `picho chat` 的当前目录执行。

如果配置：

```json
{
  "path": {
    "logs": "~/.picho/logx"
  }
}
```

日志目录就是 `~/.picho/logx`，不会变成 `~/.picho/logx/logs` 或 `~/.picho/logx/.picho/logs`。

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

#### agent.tools

自定义工具工厂列表。每个条目使用 `module:function` 或 `path.py:function`
格式；相对 `.py` 路径会按当前 executor workspace 解析。工厂会在 Runner
创建 Agent 时被调用，并收到 `ToolFactoryContext`。

| 类型 | 默认值 | 说明 |
|------|--------|------|
| string[] | `[]` | 额外挂载到 Agent 的自定义工具工厂 |

工厂必须是同步函数，返回 `Tool` 或 `list[Tool]`。如果自定义工具与内置工具重名，Runner 会报错。

导入规则：

- `my_package.tools:create_tools` 会通过 Python import 加载 `my_package.tools`，再读取 `create_tools`
- `.picho/tools/custom_tools.py:create_tools` 会按 `.py` 文件路径加载；相对路径基于 `path.executor` 对应的 workspace
- `/absolute/path/custom_tools.py:create_tools` 会按绝对文件路径加载
- 冒号右侧支持点号属性，例如 `my_package.tools:Factory.create_tools`

示例一，从已安装或可 import 的包中加载：

```json
{
  "agent": {
    "tools": ["my_project.tools.webfetch:create_tools"]
  }
}
```

示例二，从 executor workspace 下的相对路径加载。假设 `path.executor` 是
`/workspace/project`：

```json
{
  "agent": {
    "tools": [".picho/tools/custom_tools.py:create_tools"]
  }
}
```

实际加载文件为：

```text
/workspace/project/.picho/tools/custom_tools.py
```

最小示例：

```python
from picho.builtin import pi_tool


def create_tools(context):
    @pi_tool(name="workspace_info")
    def workspace_info() -> str:
        return context.workspace

    return [workspace_info]
```

配置：

```json
{
  "agent": {
    "tools": [".picho/tools/custom_tools.py:create_tools"]
  }
}
```

#### agent.builtin.tool_config.read

`read` 工具专属配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `extensions` | string[] | `[]` | 自定义 read 扩展模块列表，支持 Python 模块名或 `.py` 文件路径 |
| `video_compression.enabled` | boolean | `true` | 超大视频是否自动压缩 |
| `video_compression.trigger_size_mb` | int | `512` | 触发自动压缩的体积阈值 |
| `audio_asr.provider` | string | `"mock"` | WAV/MP3 转写 provider，可选 `mock`、`volcengine` |
| `audio_asr.language` | string/null | `null` | ASR 语言代码，例如 `zh-CN`；为空时由 provider 自动识别 |
| `audio_asr.enable_punc` | boolean | `false` | 是否启用标点 |
| `audio_asr.enable_itn` | boolean | `true` | 是否启用逆文本归一化 |
| `audio_asr.enable_ddc` | boolean | `false` | 是否启用语义顺滑 |
| `audio_asr.enable_speaker_info` | boolean | `false` | 是否启用说话人信息 |
| `audio_asr.include_utterances` | boolean | `true` | 输出中是否包含分句时间戳 |
| `audio_asr.include_words` | boolean | `false` | provider 返回词级信息时是否保留 |
| `audio_asr.vad_segment` | boolean | `false` | 是否启用 VAD 分段 |
| `audio_asr.timeout_seconds` | int | `60` | ASR 任务最大等待秒数 |
| `audio_asr.poll_interval_seconds` | int | `2` | ASR 任务轮询间隔秒数 |
| `audio_asr.volcengine.tos_bucket` | string/null | `null` | Volcengine TOS bucket；为空时读取 `DEFAULT_TOS_BUCKET` |
| `audio_asr.volcengine.tos_region` | string | `"cn-beijing"` | Volcengine TOS 区域 |
| `audio_asr.volcengine.*_env` | string | 见说明 | Volcengine 凭证环境变量名 |

`audio_asr` 规则：
- `mock` provider 不访问外部服务，适合开发和测试；输出会明确标记为 mock transcript。
- `volcengine` provider 会先把本地音频上传到 TOS，再把公开 URL 提交给豆包录音文件识别。
- Volcengine 默认读取这些环境变量：`VOLCENGINE_ACCESS_KEY`、`VOLCENGINE_SECRET_KEY`、`VOLCENGINE_SPEECH_API_KEY`、`DEFAULT_TOS_BUCKET`。
- WAV/MP3 转写结果按文件 mtime 和 ASR 关键配置缓存到 `path.cache/files`；未配置 `path.cache` 时默认是 `path.base/caches/files`。
- 每个 provider 的详细配置和使用方式见 `picho/builtin/tool/extension/read/parser/audio/*.md`。

Volcengine ASR 配置示例：

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "audio_asr": {
            "provider": "volcengine",
            "language": "zh-CN",
            "enable_punc": true,
            "volcengine": {
              "tos_bucket": "my-bucket",
              "tos_region": "cn-beijing"
            }
          }
        }
      }
    }
  }
}
```

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

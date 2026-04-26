# Builtin 模块

picho 的内置工具和技能。

## 概述

本模块提供开箱即用的内置工具和技能，供 AI Agent 直接使用。

## 架构

```
builtin/
├── __init__.py          # 模块导出
├── decorator.py         # @pi_tool 装饰器
├── security.py          # 安全工具
├── tool/                # 内置工具
│   ├── __init__.py
│   ├── read.py          # 文件读取工具
│   ├── write.py         # 文件写入工具
│   ├── edit.py          # 文件编辑工具
│   └── bash.py          # Bash 执行工具
└── skill/               # 内置技能
    ├── __init__.py
    ├── code-review/     # 代码审查技能
    ├── debug/           # 调试技能
    └── skill-creator/   # 技能创建器技能
```

## 内置工具

### read - 读取文件

读取文件内容，支持文本、图片、视频、音频、PDF 和 DOCX：

```python
# 参数
{
    "path": "文件路径（相对或绝对）",
    "offset": "起始行号（可选，从1开始）",
    "limit": "最大行数（可选）"
}
```

特性：
- 自动截断大文件（默认 2000 行或 50KB）
- 支持图片文件（jpg, png, gif, webp）
- 支持视频文件（mp4, mov, avi, mkv, webm）
- PDF/DOCX 会转换为 markdown，并缓存到 `.picho/cache/files`
- WAV/MP3 会转写为 markdown，并缓存到 `.picho/cache/files`
- 默认启用的视频压缩：当视频超过阈值时，自动使用 `ffmpeg` 保留音频并压缩后再读取；可通过 `tool_config.read.video_compression.enabled=false` 关闭
- 可通过 `tool_config.read.extensions` 注册用户自定义读取扩展
- 支持分页读取

行为说明：
- `文件不存在`等常规工具错误会以错误文本结果返回，不再直接向 agent 暴露 Python traceback
- abort 信号会继续按取消语义向上传播，由 agent loop 统一生成 aborted 结果
- PDF/DOCX 和音频转换等待过程现在能响应 abort；底层工作线程仍可能在后台自然结束

音频 ASR 配置示例：

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

说明：
- `audio_asr.provider` 可选 `mock` 或 `volcengine`，默认是 `mock`。
- Volcengine provider 会先把本地音频上传到 TOS，再把公开 URL 提交给豆包录音文件识别。
- Volcengine 凭证从环境变量读取：`VOLCENGINE_ACCESS_KEY`、`VOLCENGINE_SECRET_KEY`、`VOLCENGINE_SPEECH_API_KEY`。
- 如果省略 `audio_asr.volcengine.tos_bucket`，会使用 `DEFAULT_TOS_BUCKET`。
- 每个 provider 的详细文档位于 `tool/extension/read/parser/audio/*.md`。

视频压缩配置示例：

```json
{
  "path": {
    "cache": "."
  },
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "video_compression": {
            "enabled": true,
            "trigger_size_mb": 512
          }
        }
      }
    }
  }
}
```

说明：
- 未配置时默认启用自动压缩；设置 `enabled=false` 时，视频走原始读取链路
- 只有视频体积超过 `trigger_size_mb` 时才会触发压缩
- 需要用户本机已安装 `ffmpeg` 和 `ffprobe`
- 压缩结果会缓存，源文件未变化时可复用缓存
- `path.cache` 可选；默认使用项目 `path.base`，相对路径相对于 `path.base` 解析，绝对路径则直接使用

自定义 read 扩展示例：

```python
from pathlib import Path

from picho.builtin.tool.extension.read import ReadExtension, ReadExtensionContext
from picho.provider.types import TextContent
from picho.tool import ToolResult


def read_csv(context: ReadExtensionContext) -> ToolResult:
    content = Path(context.resolved_path).read_text(encoding="utf-8")
    return ToolResult(
        content=[TextContent(type="text", text=content)]
    )


READ_EXTENSIONS = [
    ReadExtension(
        name="csv-reader",
        extensions=[".csv"],
        execute=read_csv,
    )
]
```

对应配置：

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "extensions": [
            ".picho/read_extensions/csv_reader.py"
          ]
        }
      }
    }
  }
}
```

覆盖内置读取器：
- 自定义 read 扩展会优先于内置处理器匹配。
- 如果为 `.pdf` 或 `.docx` 注册同后缀扩展，就可以替换默认的文档转 markdown 读取链路。
- 适合需要自定义解析器、OCR 流程、版面清洗或后处理策略的场景。

### write - 写入文件

创建或覆盖文件：

```python
# 参数
{
    "path": "文件路径",
    "content": "文件内容"
}
```

特性：
- 自动创建父目录
- 覆盖已存在的文件
- 只允许写入工作区内的文件

行为说明：
- 参数校验、路径校验和写入失败会以错误文本结果返回，不再直接向 agent 暴露 Python traceback
- abort 信号会继续按取消语义向上传播，由 agent loop 统一生成 aborted 结果

### edit - 编辑文件

精确编辑文件内容：

```python
# 参数
{
    "path": "文件路径",
    "oldText": "要替换的文本（必须精确匹配）",
    "newText": "新文本"
}
```

特性：
- 精确文本匹配
- 要求文本唯一性
- 保留文件其他内容
- 只允许编辑工作区内的文件

行为说明：
- 参数校验、匹配失败和写回失败会以错误文本结果返回，不再直接向 agent 暴露 Python traceback
- abort 信号会继续按取消语义向上传播，由 agent loop 统一生成 aborted 结果

### bash - 执行命令

执行 bash 命令：

```python
# 参数
{
    "command": "Bash 命令",
    "timeout": "超时时间（秒，可选）"
}
```

特性：
- 在指定工作空间执行
- 自动截断输出（默认 2000 行或 50KB）
- 支持超时控制

行为说明：
- 非零退出码和执行失败会以错误文本结果返回，不再直接向 agent 暴露 Python traceback
- abort 信号会继续按取消语义向上传播，由 agent loop 统一生成 aborted 结果

## 内置技能

### code-review

代码审查技能，用于合并请求和代码差异审查：

```python
# 加载技能
from picho.builtin.skill import load_builtin_skills

result = load_builtin_skills(["code-review"])
```

### debug

调试技能，用于排查复杂问题：

```python
result = load_builtin_skills(["debug"])
```

### skill-creator

创建新技能的技能：

```python
result = load_builtin_skills(["skill-creator"])
```

## 使用方式

### 创建所有内置工具

```python
from picho.builtin.tool import create_builtin_tools, HostExecutor

executor = HostExecutor(cwd="/path/to/workspace")
tools = create_builtin_tools(executor)
```

### 创建单个工具

```python
from picho.builtin.tool import (
    create_read_tool,
    create_write_tool,
    create_edit_tool,
    create_bash_tool,
    HostExecutor,
)

executor = HostExecutor(cwd="/path/to/workspace")

read_tool = create_read_tool(executor)
write_tool = create_write_tool(executor)
edit_tool = create_edit_tool(executor)
bash_tool = create_bash_tool(executor)
```

### 加载内置技能

```python
from picho.builtin.skill import load_builtin_skills

# 加载所有内置技能
result = load_builtin_skills()

# 加载特定技能
result = load_builtin_skills(["code-review", "debug"])

for skill in result.skills:
    print(f"Loaded: {skill.name}")
```

### 使用 @pi_tool 装饰器

使用装饰器创建自定义工具：

```python
from picho.builtin import pi_tool


@pi_tool(
    name="my_tool",
    description="My custom tool",
)
async def my_tool_execute(params: dict) -> str:
    return "Result"
```

## 许可证

MIT

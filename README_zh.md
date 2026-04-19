# picho

`picho`是一个极简的Agent框架，起初只是[`pi-mono`](https://github.com/badlogic/pi-mono)的一个python实现，并融合了[`google-adk`](https://github.com/google/adk-python)的一些设计理念，后续作出了更多的扩展，主要面向通用执行型Agent场景或多模态场景，`picho`对文件读取作了专门的优化，目的是用更简单的方式来实现一个Agent。

## 设计理念

picho的设计理念是尽可能**直接**，以及尽可能的**简单**

- 直接

大多数框架中，读取 PDF 或 DOCX 等文件需要两步：找到对应的 skill、解析文件，再由 read skill 处理解析后的产物。我们打算最的更直接一点，让`picho`直接对read tool进行优化：

- 支持文本与图片
- **安装扩展后**还可直接读取 PDF 和 DOCX。
- 视频方面也做了专门优化，，`picho` 做了专门的视频压缩（同样是模型无感知的）扩展了模型对视频读取的上限，通过压缩，可以让模型读取更大体积的视频。
  - 注：目前这一优化只对火山方舟模型奏效。
- 后续计划增加对音频、PPTX 等文件类型的支持。

插件方面
如果你不希望使用内置的 read 扩展，也没问题，你可以自己写新的 read extension，支持新的文件类型，或者直接替换现有的读取链路。

当然如果你真的更倾向于用 skill 来处理文件，也完全可以。内置 `read` 更适合做通用、直接的文件读取；skill 更适合封装某个领域里的专门流程、多步处理，或者和其他工具组合起来完成更复杂的工作。两者并不冲突。

- 简单

简单是picho最核心的设计理念之一，而这一点是多方面的，首先是AgentLoop方面

picho的agent loop参考了 pi-mono的思路，其核心可以简化为

```
while True:
    response = model(context)      # 调用 LLM 获取响应
    context += response            # 追加到上下文

    if response.tool_calls:
        results = execute(response.tool_calls)
        context += results         # 执行工具并追加结果
    else:
        break                      # 无工具调用时结束
```

整个循环核心十分简单，不考虑复杂的编排设计，但留下了 hook 接入点，允许在循环中嵌入自定义控制逻辑。

另一方面体现在扩展包上：除视频压缩、音频理解等必须依赖 ffmpeg 或线上服务的场景外，其他如 PDF、DOCX 等，picho 都尽量在纯 Python 范围内解决，避免引入额外的第三方软件。

## 快速开始

### 安装

推荐通过uv安装

```bash
# 安装
uv add picho
# 如果你想要支持原生read pdf、docx的需求
uv add picho["extra"]
```

### 使用方式

`picho` 常见有三种使用方式：基于配置文件直接启动 CLI、通过 Python 代码动态构造 `Runner`，以及将 `Runner` 暴露为 API 服务。

完整配置项、字段说明和扩展示例见 [picho/config.md](./picho/config.md)。

#### 1. 配置 `config.json` 后直接 `picho chat`

这是最直接的使用方式：准备配置文件后，直接启动交互会话。

`picho chat` 默认会按以下顺序查找配置：

- 当前目录下的 `.picho/config.json`
- 当前目录下的 `config.json`
- 用户目录下的 `~/.picho/config.json`

最小配置示例如下：

```json
{
  "path": {
    "base": ".",
    "executor": ".",
    "skills": [".picho/skills"]
  },
  "agent": {
    "model": {
      "model_provider": "ark-responses",
      "model_name": "doubao-seed-2-0-lite-260215",
      "base_url": "https://ark.cn-beijing.volces.com/api/v3",
      "api_key": "YOUR_ARK_API_KEY",
      "input_types": ["text", "image", "video"]
    },
    "instructions": "你是一个简洁可靠的 AI 助手。",
    "builtin": {
      "tool": ["read", "write", "bash", "edit"],
      "skill": ["code-review", "debug", "skill-creator"]
    }
  },
  "session_manager": {
    "persist": true
  }
}
```

启动命令：

```bash
uv run picho chat
```

如果希望先生成配置模板，可以执行：

```bash
uv run picho init
```

关于 `path`、`builtin`、`tool_config.read.extensions`、`executor` 等字段的完整说明，见 [picho/config.md](./picho/config.md)。

#### 2. 配置 + `Runner` 的 Python 代码方式

如果需要动态生成配置、在启动前注入自定义逻辑，或者不希望将完整配置写入 JSON 文件，可以直接通过 Python 代码创建 `Runner`，再交给 CLI 使用。

示例文件 `my_runner.py`：

```python
import os

from picho.runner import Runner


config = {
    "path": {
        "base": ".",
        "executor": ".",
        "skills": [".picho/skills"]
    },
    "agent": {
        "model": {
            "model_provider": "ark-responses",
            "model_name": "doubao-seed-2-0-lite-260215",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": os.getenv("ARK_API_KEY"),
            "input_types": ["text", "image", "video"]
        },
        "instructions": "你是一个有用的助手。",
        "builtin": {
            "tool": ["read", "write", "bash", "edit"],
            "skill": ["code-review", "debug"]
        }
    },
    "session_manager": {
        "persist": true
    }
}

runner = Runner(config_type="dict", config=config)
```

启动命令：

```bash
uv run picho chat -r my_runner.py
```

`-r` 接收一个 Python 文件路径，该文件必须导出名为 `runner` 的变量。

配置字段定义与说明仍以 [picho/config.md](./picho/config.md) 为准。

#### 3. API 方式

如果需要将 `picho` 集成到服务端应用中，可以直接将 `Runner` 包装为 FastAPI 服务。内置 `APIServer` 已提供健康检查、会话管理和 SSE 流式对话接口。 （这部分接口设计参考了google-adk）

示例文件 `api_server.py`：

```python
from picho.api.server import APIServer
from picho.runner import Runner


runner = Runner(config_type="json", config=".picho/config.json")
server = APIServer(runner, host="127.0.0.1", port=8000)
server.run()
```

启动命令：

```bash
uv run python api_server.py
```

快速验证：

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/sessions
```

如需流式调用，可进一步请求 `/run_sse`。API 设计与端点说明见 [picho/api/README\_zh.md](./picho/api/README_zh.md)。

## 项目结构

项目整体可以按“入口层 -> 执行层 -> 工具与 skill -> 会话与服务封装”的顺序理解：

```text
picho/
├── picho/
│   ├── agent/          # Agent 与 agent loop
│   ├── api/            # FastAPI API 组装与路由
│   ├── builtin/        # 内置 tool 与内置 skill
│   ├── cli/            # picho init / picho chat / TUI
│   ├── observability/  # 观测与 telemetry
│   ├── provider/       # 模型 provider 抽象
│   ├── runner/         # Runner，对外最常用的编排入口
│   ├── session/        # 会话持久化、分支、压缩
│   ├── skills/         # 自定义 skill 加载与格式化
│   ├── tool/           # 通用 tool 抽象、执行器与结果处理
│   ├── utils/          # 辅助工具
│   ├── config.py       # 配置模型
│   └── config.md       # 配置说明
├── tests/              # 测试
├── README.md
└── README_zh.md
```

各模块职责如下：

- [picho/cli/README\_zh.md](./picho/cli/README_zh.md)：命令行入口，主要提供 `picho init` 与 `picho chat`。
- [picho/runner/README\_zh.md](./picho/runner/README_zh.md)：最常用的程序化入口，负责组织配置、Agent、Session、skills 与工具。
- [picho/agent/README\_zh.md](./picho/agent/README_zh.md)：Agent 本体与 agent loop，负责模型调用、工具执行和上下文推进。
- [picho/provider/README\_zh.md](./picho/provider/README_zh.md)：模型适配层，统一不同 provider 的调用方式。
- [picho/session/README\_zh.md](./picho/session/README_zh.md)：会话状态管理、持久化、分支切换与上下文压缩。
- [picho/api/README\_zh.md](./picho/api/README_zh.md)：将 `Runner` 暴露为 HTTP / SSE 接口，适合服务化集成。
- [picho/observability/README\_zh.md](./picho/observability/README_zh.md)：日志、序列化与 telemetry 相关能力。
- [picho/tool/README\_zh.md](./picho/tool/README_zh.md)：通用工具协议、执行器与结果裁剪，不限于内置工具。
- [picho/builtin/README\_zh.md](./picho/builtin/README_zh.md)：开箱即用的内置能力，包括 builtin tool 与 builtin skill。
- [picho/skills/README\_zh.md](./picho/skills/README_zh.md)：skill 加载器，负责读取并格式化基于 markdown + frontmatter 的 skill。
- [tests/README\_zh.md](./tests/README_zh.md)：测试约定与测试目录说明。

关于 builtin tool、skill 与内置 `read` 的关系，可以概括为：

- `builtin tool` 是真正可执行的能力，比如 `read`、`write`、`edit`、`bash`。
- 内置 `read` 是默认的一等文件读取能力，适合直接读取文本、图片，以及通过扩展读取 PDF、DOCX、视频等内容。
- `skill` 更接近任务级的指令模板或工作流封装，适合代码审查、调试、领域分析以及更复杂的文件处理流程。
- 两者是互补关系而非替代关系：可直接读取的内容优先交给 `read`；需要专门流程、额外规则、领域知识或多步编排时，再使用 skill 更合适。
  - 这里我想补充一些私货与个人的理解：内置 `read` 像一双眼睛，用来看地球上的万物；而读文件专用的 skill 更像望远镜，当你需要仰望星空、处理更专业或更遥远的目标时，就可以拿起来使用。我们认为两者服务的应当是不同层次的问题，并不相互排斥，而且也不应该让skill来承担常规的read工作。这有些杀鸡用牛刀的意味了。


- `read` 支持扩展与替换：可通过 `agent.builtin.tool_config.read.extensions` 注册新的读取扩展；自定义扩展会优先于内置读取器匹配，因此既可以支持新文件类型，也可以替换 `.pdf`、`.docx` 等默认读取链路。
- `skill` 也同样支持扩展：除了内置 skill 之外，你还可以把自定义 skill 放到 `.picho/skills`，或者通过 `path.skills` 指向别的目录。


## Notes

目前项目仍处于早期开发阶段，provider方面只有ark-responses支持完善，尚无法直接投入使用。
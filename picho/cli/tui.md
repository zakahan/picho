# picho TUI 配置说明

## 完整配置示例

```json
{
  "chat": {
    "show_thinking": true,
    "show_tool_execution": true,
    "show_tool_args": "low",
    "show_tool_result": "low",
    "stream_output": true,
    "prompt_prefix": "You",
    "assistant_name": "picho"
  },
  "display": {
    "theme": "default",
    "color_enabled": true,
    "show_banner": true,
    "show_usage": true
  },
  "log": {
    "console_output": false
  }
}
```

## 配置文件位置

`load_cli_config()` 会按以下顺序查找 TUI 配置：

1. CLI 选项 `--tui-config` 指定的路径
2. 当前工作区的 `.picho/tui.json`
3. 用户目录下的 `~/.picho/tui.json`

如果三处都不存在，首次运行时会自动在当前工作区创建 `.picho/tui.json`。

使用 `--tui-config` 指定路径：

```bash
picho chat --tui-config /path/to/my-tui.json
```

---

## 配置项详解

### chat

聊天展示与交互行为配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `show_thinking` | boolean | `true` | 是否显示模型的 thinking 流式内容 |
| `show_tool_execution` | boolean | `true` | 是否显示工具调用和工具结果区域 |
| `show_tool_args` | `"off"` \| `"low"` \| `"all"` | `"off"` | 工具参数的展示粒度 |
| `show_tool_result` | `"off"` \| `"low"` \| `"all"` | `"off"` | 工具结果的展示粒度 |
| `stream_output` | boolean | `true` | 是否实时流式显示 thinking / assistant 内容；关闭后只在消息结束时一次性输出最终结果 |
| `prompt_prefix` | string | `"You"` | 输入框前缀，同时作为用户消息块标题 |
| `assistant_name` | string | `"picho"` | assistant 输出框标题和状态栏显示名称 |

#### `show_tool_args` / `show_tool_result` 规则

- `off`: 不显示对应内容
- `low`: 显示截断后的简略内容，适合日常使用
- `all`: 尽量显示完整内容，适合排查问题

#### `stream_output` 规则

- `true`: assistant 和 thinking 按增量流式输出
- `false`: 忽略中间增量，只在 `message_end` 时输出完整 assistant 消息
- `false` 时，工具调用和工具结果仍然按事件实时显示

---

### display

TUI 外观配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | `"default"` \| `"dark"` \| `"light"` \| `"ocean"` \| `"forest"` \| `"mono"` | `"default"` | 主题名称 |
| `color_enabled` | boolean | `true` | 是否启用 ANSI / rich 彩色输出 |
| `show_banner` | boolean | `true` | 启动时是否显示顶部 welcome banner |
| `show_usage` | boolean | `true` | assistant 消息底部是否显示 token usage 摘要 |

#### `theme` 说明

- `default`: 当前默认的金色 / 铜色 Hermes 风格
- `dark`: 深色蓝灰风格
- `light`: 浅色高对比风格
- `ocean`: 青蓝海洋风格
- `forest`: 绿色终端风格
- `mono`: 黑白灰极简风格

#### `color_enabled` 规则

- `true`: 使用主题颜色渲染 banner、状态栏、消息框、工具日志
- `false`: 保留布局和边框结构，但输出尽量退化为无色文本，适合低色彩终端或日志采集场景

#### `show_usage` 规则

- `true`: assistant 输出底部会显示类似 `tokens in=123 out=456 cache r=0 w=0`
- `false`: assistant 输出底部只显示收尾边框，不附带 token 摘要

---

### log

CLI 日志输出配置。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `console_output` | boolean | `false` | 是否把内部日志同时输出到当前终端 |

`console_output` 主要影响 Python logging 的控制台输出，不改变聊天 transcript 的展示方式。

---

## 最小配置示例

### 只改主题

```json
{
  "display": {
    "theme": "ocean"
  }
}
```

### 关闭颜色与 banner

```json
{
  "display": {
    "color_enabled": false,
    "show_banner": false
  }
}
```

### 关闭流式输出，只看最终答案

```json
{
  "chat": {
    "stream_output": false,
    "show_thinking": false
  }
}
```

### 调整工具展示粒度

```json
{
  "chat": {
    "show_tool_execution": true,
    "show_tool_args": "low",
    "show_tool_result": "all"
  }
}
```

### 自定义用户和 assistant 名称

```json
{
  "chat": {
    "prompt_prefix": "Bytedance",
    "assistant_name": "my-agent"
  }
}
```

---

## 推荐配置

### 日常开发

```json
{
  "chat": {
    "show_thinking": false,
    "show_tool_execution": true,
    "show_tool_args": "low",
    "show_tool_result": "low",
    "stream_output": true
  },
  "display": {
    "theme": "default",
    "color_enabled": true,
    "show_banner": true,
    "show_usage": true
  }
}
```

### 低干扰模式

```json
{
  "chat": {
    "show_thinking": false,
    "show_tool_execution": true,
    "show_tool_args": "off",
    "show_tool_result": "off",
    "stream_output": false
  },
  "display": {
    "theme": "mono",
    "color_enabled": false,
    "show_banner": false,
    "show_usage": false
  }
}
```

# picho Observability

picho Observability 基于 OpenTelemetry，为 Agent 执行过程提供本地 tracing 能力，主要用于开发期调试和性能分析，重点覆盖：

- invocation 级链路树
- LLM 时延指标，例如 TTFT、TPOT
- token 消耗
- 工具调用耗时
- 通过 CLI 和本地 Web Viewer 做可视化查看

## 架构概览

```text
Runner
  │
  ├── configure_observability()
  │
  ▼
OpenTelemetry TracerProvider
  │
  ├── BatchSpanProcessor
  │     - 异步导出
  │     - best effort
  │     - 不阻塞主链路
  │
  ▼
LocalSqliteSpanExporter
  │
  ▼
.picho/telemetry/spans.db
```

## 当前会记录什么

当前 tracing 模型会记录这些 spans：

- `picho.agent.run`
  - 一次完整的 agent invocation
- `picho.agent.turn`
  - agent loop 中的一轮 turn
- `picho.llm.stream`
  - 一次模型请求/流式响应
- `picho.tool.execute`
  - 一次工具调用

每个 span 可能包含：

- `session_id`
- `invocation_id`
- duration
- status
- model 或 tool 元数据
- token usage
- message、tool args、tool result 的 preview

## 存储路径

默认情况下 telemetry 会写到：

```text
<path.telemetry or path.base/telemetry>/spans.db
```

这个路径由 `PathConfig.telemetry` 控制。

## 配置

可以显式启用或关闭 telemetry：

```json
{
  "path": {
    "base": "/path/to/project/.picho",
    "telemetry": "/path/to/project/.picho/telemetry"
  },
  "observability": {
    "enabled": true
  }
}
```

关键配置项：

- `path.telemetry`
  - telemetry 数据存储根目录
- `observability.enabled`
  - 是否启用 tracing

如果 `observability.enabled` 为 `false`，picho 会跳过 tracer 初始化。

## 依赖安装

OpenTelemetry 相关包必须安装在当前运行的 Python 环境里：

```bash
uv sync
```

如果 OpenTelemetry 没有安装，picho 只会打印 warning，并自动退化成 no-op tracer，不会阻塞主进程。

## CLI 命令

可以通过下面的方式使用 telemetry CLI：

```bash
uv run python -m picho.cli telemetry <command>
```

或者在 editable install 之后：

```bash
pi telemetry <command>
```

### `telemetry info`

查看 telemetry 存储状态：

```bash
uv run python -m picho.cli telemetry info
```

### `telemetry latest`

查看最近一次 invocation 的摘要：

```bash
uv run python -m picho.cli telemetry latest
```

### `telemetry invocation <invocation_id>`

查看某次 invocation 的详细链路：

```bash
pi telemetry invocation 243e378b-c5bc-4dfd-b73a-4149b7248ceb
```

### `telemetry session [session_id]`

查看某个 session 下最近的 invocation 列表：

```bash
pi telemetry session
pi telemetry session d58ef81d
```

### `telemetry spans`

查看原始 spans：

```bash
pi telemetry spans --limit 20
pi telemetry spans --session-id d58ef81d
pi telemetry spans --invocation-id 243e378b-c5bc-4dfd-b73a-4149b7248ceb
```

### `telemetry serve`

启动本地 Web Viewer：

```bash
pi telemetry serve
pi telemetry serve --host 127.0.0.1 --port 16853
```

这个 viewer 可以用来查看：

- sessions
- 某个 session 下的 invocations
- span tree
- LLM 调用指标
- tool 调用摘要

## 常用指标

这些字段最常用：

- `picho.duration.ms`
  - invocation、turn、model call、tool call 的耗时
- `picho.ttft.ms`
  - 首 token 时延
- `picho.tpot.ms`
  - 每个输出 token 的平均时间
- `gen_ai.usage.input_tokens`
  - 输入 token
- `gen_ai.usage.output_tokens`
  - 输出 token
- `gen_ai.provider.name`
  - provider 名称
- `gen_ai.request.model`
  - model 名称
- `gen_ai.tool.name`
  - tool 名称

## 关于 `UNSET`

`UNSET` 是 OpenTelemetry 的默认 span status，表示没有显式标记成功或失败，不代表这个 span 出错。

picho 现在已经会把成功 span 标成 `OK`，但数据库里旧的记录不会自动改写，所以你仍可能在老数据中看到 `UNSET`。重新跑一次新的 session 或 invocation，就会看到更新后的状态行为。

## 为什么不会阻塞主进程

Observability 是 best-effort 设计：

- spans 通过 `BatchSpanProcessor` 导出
- 导出是异步的
- exporter 失败只会打 warning
- tracing 不应该影响 agent 主流程

也就是说，即便 exporter 失败，最坏情况也只是丢失部分 observability 数据，而不是让主流程失败。

## 当前限制

- 当前 Web Viewer 还是轻量的本地检查工具，还不是 Jaeger 那种完整 waterfall UI
- 当 schema 或 status 行为变化时，历史 spans 不会被自动重写
- preview 字段会做截断和安全处理，不会完整保留所有原始内容

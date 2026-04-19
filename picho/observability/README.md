# picho Observability

picho Observability provides local tracing for agent execution using OpenTelemetry. It is designed for development-time debugging and performance analysis, with a focus on:

- Invocation-level trace trees
- LLM latency metrics such as TTFT and TPOT
- Token usage
- Tool execution timing
- Local inspection through CLI and a lightweight web viewer

## Architecture Overview

```text
Runner
  │
  ├── configure_observability()
  │
  ▼
OpenTelemetry TracerProvider
  │
  ├── BatchSpanProcessor
  │     - async export
  │     - best effort
  │     - does not block agent execution
  │
  ▼
LocalSqliteSpanExporter
  │
  ▼
.picho/telemetry/spans.db
```

## What Gets Traced

The current tracing model records these spans:

- `picho.agent.run`
  - One invocation of the agent
- `picho.agent.turn`
  - One turn inside the agent loop
- `picho.llm.stream`
  - One model request/stream
- `picho.tool.execute`
  - One tool call

Each span may include:

- `session_id`
- `invocation_id`
- duration
- status
- model or tool metadata
- token usage
- preview fields for messages, tool args, and tool results

## Storage Layout

By default telemetry is written to:

```text
<path.telemetry or path.base>/.picho/telemetry/spans.db
```

This is configured through `PathConfig.telemetry`.

## Configuration

Telemetry can be enabled or disabled explicitly:

```json
{
  "path": {
    "base": "/path/to/project",
    "telemetry": "/path/to/project"
  },
  "observability": {
    "enabled": true
  }
}
```

Relevant config fields:

- `path.telemetry`
  - telemetry storage root
- `observability.enabled`
  - whether tracing is enabled

If `observability.enabled` is `false`, picho will skip tracer initialization.

## Dependencies

OpenTelemetry packages must exist in the active Python environment:

```bash
uv sync
```

If OpenTelemetry is not installed, picho will log a warning and fall back to a no-op tracer instead of blocking the main process.

## CLI Commands

Use the telemetry CLI through:

```bash
uv run python -m picho.cli telemetry <command>
```

Or, after editable install:

```bash
pi telemetry <command>
```

### `telemetry info`

Shows storage info:

```bash
uv run python -m picho.cli telemetry info
```

### `telemetry latest`

Shows the latest invocation summary:

```bash
uv run python -m picho.cli telemetry latest
```

### `telemetry invocation <invocation_id>`

Shows one invocation in detail:

```bash
pi telemetry invocation 243e378b-c5bc-4dfd-b73a-4149b7248ceb
```

### `telemetry session [session_id]`

Lists recent invocations for a session:

```bash
pi telemetry session
pi telemetry session d58ef81d
```

### `telemetry spans`

Lists raw spans:

```bash
pi telemetry spans --limit 20
pi telemetry spans --session-id d58ef81d
pi telemetry spans --invocation-id 243e378b-c5bc-4dfd-b73a-4149b7248ceb
```

### `telemetry serve`

Starts a local web viewer:

```bash
pi telemetry serve
pi telemetry serve --host 127.0.0.1 --port 16853
```

The viewer lets you inspect:

- sessions
- invocations under a session
- span tree
- LLM call metrics
- tool call summaries

## Common Metrics

The following fields are commonly useful:

- `picho.duration.ms`
  - duration for invocation, turn, model call, or tool call
- `picho.ttft.ms`
  - time to first token
- `picho.tpot.ms`
  - time per output token
- `gen_ai.usage.input_tokens`
  - input token usage
- `gen_ai.usage.output_tokens`
  - output token usage
- `gen_ai.provider.name`
  - provider name
- `gen_ai.request.model`
  - model name
- `gen_ai.tool.name`
  - tool name

## About `UNSET`

`UNSET` is the default OpenTelemetry span status when no explicit success or error status is set.

picho now marks successful spans as `OK`, but older rows already stored in the database may still show `UNSET`. Run a new session or invocation to see the updated status behavior.

## Non-Blocking Behavior

Observability is intentionally best-effort:

- spans are exported through `BatchSpanProcessor`
- export runs asynchronously
- exporter failures are logged as warnings
- tracing must not break agent execution

If the exporter fails, the worst case should be losing observability data, not breaking the main workflow.

## Current Limitations

- The web viewer is currently a lightweight local inspector, not a full Jaeger-style waterfall UI
- Existing stored spans are not rewritten when schema or status behavior changes
- Preview fields are intentionally truncated and sanitized for safety

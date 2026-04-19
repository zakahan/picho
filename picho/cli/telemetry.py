from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ..config import Config


@dataclass
class SpanRow:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    kind: str | None
    start_time_unix_nano: int
    end_time_unix_nano: int
    duration_ms: float | None
    status_code: str | None
    status_description: str | None
    session_id: str | None
    invocation_id: str | None
    attributes: dict[str, Any]
    events: list[dict[str, Any]]


def _find_config() -> str | None:
    candidates = [
        Path.cwd() / ".picho" / "config.json",
        Path.cwd() / "config.json",
        Path.home() / ".picho" / "config.json",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _load_config(config_path: str | None) -> Config:
    resolved = config_path or _find_config()
    if not resolved:
        raise click.ClickException(
            "No config file found. Use --config or create .picho/config.json."
        )
    with open(resolved, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return Config.from_dict(data)


def _telemetry_db_path(config: Config) -> Path:
    return Path(config.path.get_telemetry_dir()) / "spans.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise click.ClickException(
            f"Telemetry DB not found: {db_path}. Run picho with observability enabled first."
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _load_json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_span(row: sqlite3.Row) -> SpanRow:
    return SpanRow(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row["parent_span_id"],
        name=row["name"],
        kind=row["kind"],
        start_time_unix_nano=row["start_time_unix_nano"],
        end_time_unix_nano=row["end_time_unix_nano"],
        duration_ms=row["duration_ms"],
        status_code=row["status_code"],
        status_description=row["status_description"],
        session_id=row["session_id"],
        invocation_id=row["invocation_id"],
        attributes=_load_json(row["attributes_json"], {}),
        events=_load_json(row["events_json"], []),
    )


def _query_spans(
    conn: sqlite3.Connection,
    *,
    invocation_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    limit: int | None = None,
) -> list[SpanRow]:
    clauses: list[str] = []
    params: list[Any] = []
    if invocation_id:
        clauses.append("invocation_id = ?")
        params.append(invocation_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)

    sql = "SELECT * FROM spans"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY start_time_unix_nano"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_span(row) for row in rows]


def _get_latest_invocation_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT invocation_id
        FROM spans
        WHERE invocation_id IS NOT NULL AND invocation_id != ''
        ORDER BY start_time_unix_nano DESC
        LIMIT 1
        """
    ).fetchone()
    return row["invocation_id"] if row else None


def _get_latest_session_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT session_id
        FROM spans
        WHERE session_id IS NOT NULL AND session_id != ''
        ORDER BY start_time_unix_nano DESC
        LIMIT 1
        """
    ).fetchone()
    return row["session_id"] if row else None


def _fmt_ts(timestamp_ns: int | None) -> str:
    if not timestamp_ns:
        return "-"
    return (
        datetime.fromtimestamp(
            timestamp_ns / 1_000_000_000,
            tz=timezone.utc,
        )
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "-"
    try:
        total_ms = float(value)
        if total_ms < 1000:
            if total_ms >= 100:
                return f"{total_ms:.0f}ms"
            if total_ms >= 10:
                return f"{total_ms:.1f}ms"
            return f"{total_ms:.2f}ms"

        total_seconds = total_ms / 1000
        if total_seconds < 60:
            return f"{total_seconds:.2f}s"

        minutes = int(total_seconds // 60)
        seconds = total_seconds - (minutes * 60)
        return f"{minutes}m {seconds:.1f}s"
    except (TypeError, ValueError):
        return str(value)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def _echo_kv(key: str, value: Any) -> None:
    click.echo(f"{key:<18} {value}")


def _span_status(span: SpanRow) -> str:
    return str(span.attributes.get("picho.status") or span.status_code or "-")


def _build_depths(spans: list[SpanRow]) -> dict[str, int]:
    by_parent: dict[str | None, list[SpanRow]] = defaultdict(list)
    for span in spans:
        by_parent[span.parent_span_id].append(span)

    for children in by_parent.values():
        children.sort(key=lambda item: item.start_time_unix_nano)

    depths: dict[str, int] = {}

    def walk(parent_id: str | None, depth: int) -> None:
        for child in by_parent.get(parent_id, []):
            if child.span_id in depths:
                continue
            depths[child.span_id] = depth
            walk(child.span_id, depth + 1)

    walk(None, 0)
    for span in spans:
        depths.setdefault(span.span_id, 0)
    return depths


def _print_span_tree(spans: list[SpanRow]) -> None:
    if not spans:
        click.echo("No spans found.")
        return

    click.echo("\nSpan Tree")
    depths = _build_depths(spans)
    for span in spans:
        depth = depths.get(span.span_id, 0)
        indent = "  " * depth
        click.echo(
            f"{indent}- {span.name} | {_fmt_ms(span.duration_ms)} | {_span_status(span)}"
        )


def _print_llm_summary(spans: list[SpanRow]) -> None:
    llm_spans = [span for span in spans if span.name == "picho.llm.stream"]
    if not llm_spans:
        return

    click.echo("\nLLM Calls")
    for index, span in enumerate(llm_spans, start=1):
        attrs = span.attributes
        click.echo(
            "  ".join(
                [
                    f"#{index}",
                    f"model={attrs.get('gen_ai.request.model', '-')}",
                    f"provider={attrs.get('gen_ai.provider.name', '-')}",
                    f"dur={_fmt_ms(attrs.get('picho.duration.ms', span.duration_ms))}",
                    f"ttft={_fmt_ms(attrs.get('picho.ttft.ms'))}",
                    f"tpot={_fmt_ms(attrs.get('picho.tpot.ms'))}",
                    f"in={_fmt_num(attrs.get('gen_ai.usage.input_tokens'))}",
                    f"out={_fmt_num(attrs.get('gen_ai.usage.output_tokens'))}",
                ]
            )
        )


def _print_tool_summary(spans: list[SpanRow]) -> None:
    tool_spans = [span for span in spans if span.name == "picho.tool.execute"]
    if not tool_spans:
        return

    click.echo("\nTool Calls")
    for index, span in enumerate(tool_spans, start=1):
        attrs = span.attributes
        click.echo(
            "  ".join(
                [
                    f"#{index}",
                    f"tool={attrs.get('gen_ai.tool.name', '-')}",
                    f"dur={_fmt_ms(attrs.get('picho.duration.ms', span.duration_ms))}",
                    f"status={attrs.get('picho.status', '-')}",
                    f"args={attrs.get('picho.tool.args', '-')}",
                ]
            )
        )


def _print_invocation_summary(spans: list[SpanRow]) -> None:
    if not spans:
        raise click.ClickException("No spans found for the requested invocation.")

    first = spans[0]
    last = spans[-1]
    root = next((span for span in spans if span.parent_span_id is None), first)
    root_attrs = root.attributes

    click.echo("Invocation Summary")
    _echo_kv("session_id", first.session_id or "-")
    _echo_kv("invocation_id", first.invocation_id or "-")
    _echo_kv("trace_id", first.trace_id)
    _echo_kv("start", _fmt_ts(first.start_time_unix_nano))
    _echo_kv("end", _fmt_ts(last.end_time_unix_nano))
    _echo_kv("duration", _fmt_ms(root_attrs.get("picho.duration.ms", root.duration_ms)))
    _echo_kv("status", root_attrs.get("picho.status", root.status_code or "-"))

    _print_span_tree(spans)
    _print_llm_summary(spans)
    _print_tool_summary(spans)


def _summarize_invocations_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          invocation_id,
          MIN(start_time_unix_nano) AS start_time_unix_nano,
          MAX(end_time_unix_nano) AS end_time_unix_nano,
          MAX(duration_ms) AS duration_ms,
          COUNT(*) AS span_count
        FROM spans
        WHERE session_id = ? AND invocation_id IS NOT NULL AND invocation_id != ''
        GROUP BY invocation_id
        ORDER BY start_time_unix_nano DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return [
        {
            "invocation_id": row["invocation_id"],
            "start_time_unix_nano": row["start_time_unix_nano"],
            "end_time_unix_nano": row["end_time_unix_nano"],
            "start": _fmt_ts(row["start_time_unix_nano"]),
            "end": _fmt_ts(row["end_time_unix_nano"]),
            "duration_ms": row["duration_ms"],
            "duration": _fmt_ms(row["duration_ms"]),
            "span_count": row["span_count"],
        }
        for row in rows
    ]


def _list_sessions(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          session_id,
          MAX(end_time_unix_nano) AS latest_time_unix_nano,
          COUNT(DISTINCT invocation_id) AS invocation_count,
          COUNT(*) AS span_count
        FROM spans
        WHERE session_id IS NOT NULL AND session_id != ''
        GROUP BY session_id
        ORDER BY latest_time_unix_nano DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "session_id": row["session_id"],
            "latest_time_unix_nano": row["latest_time_unix_nano"],
            "latest_time": _fmt_ts(row["latest_time_unix_nano"]),
            "invocation_count": row["invocation_count"],
            "span_count": row["span_count"],
        }
        for row in rows
    ]


def _invocation_payload(spans: list[SpanRow]) -> dict[str, Any]:
    if not spans:
        raise click.ClickException("No spans found for the requested invocation.")

    depths = _build_depths(spans)
    first = spans[0]
    last = spans[-1]
    root = next((span for span in spans if span.parent_span_id is None), first)
    root_attrs = root.attributes

    llm_calls = []
    tool_calls = []
    span_items = []

    for span in spans:
        attrs = span.attributes
        if span.name == "picho.llm.stream":
            llm_calls.append(
                {
                    "name": span.name,
                    "duration_ms": attrs.get("picho.duration.ms", span.duration_ms),
                    "ttft_ms": attrs.get("picho.ttft.ms"),
                    "tpot_ms": attrs.get("picho.tpot.ms"),
                    "model": attrs.get("gen_ai.request.model"),
                    "provider": attrs.get("gen_ai.provider.name"),
                    "input_tokens": attrs.get("gen_ai.usage.input_tokens"),
                    "output_tokens": attrs.get("gen_ai.usage.output_tokens"),
                    "finish_reasons": attrs.get("gen_ai.response.finish_reasons"),
                    "preview": attrs.get("picho.output.message.preview"),
                }
            )
        if span.name == "picho.tool.execute":
            tool_calls.append(
                {
                    "name": attrs.get("gen_ai.tool.name"),
                    "duration_ms": attrs.get("picho.duration.ms", span.duration_ms),
                    "status": attrs.get("picho.status", _span_status(span)),
                    "args": attrs.get("picho.tool.args"),
                    "result_preview": attrs.get("picho.tool.result_preview"),
                }
            )

        span_items.append(
            {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "name": span.name,
                "depth": depths.get(span.span_id, 0),
                "duration_ms": span.duration_ms,
                "status": _span_status(span),
                "kind": span.kind,
                "attributes": attrs,
                "events": span.events,
            }
        )

    return {
        "summary": {
            "session_id": first.session_id,
            "invocation_id": first.invocation_id,
            "trace_id": first.trace_id,
            "start_time_unix_nano": first.start_time_unix_nano,
            "end_time_unix_nano": last.end_time_unix_nano,
            "start": _fmt_ts(first.start_time_unix_nano),
            "end": _fmt_ts(last.end_time_unix_nano),
            "duration_ms": root_attrs.get("picho.duration.ms", root.duration_ms),
            "status": root_attrs.get("picho.status", _span_status(root)),
        },
        "spans": span_items,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
    }


def _viewer_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>picho Telemetry Viewer</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #0b1020; color: #e5e7eb; }
    .layout { display: grid; grid-template-columns: 320px 360px 1fr; height: 100vh; }
    .panel { border-right: 1px solid #1f2937; overflow: auto; padding: 16px; }
    .panel:last-child { border-right: none; }
    h1, h2, h3 { margin: 0 0 12px; font-size: 16px; }
    .item { padding: 10px 12px; margin-bottom: 8px; border: 1px solid #1f2937; border-radius: 10px; cursor: pointer; background: #111827; }
    .item:hover, .item.active { border-color: #60a5fa; background: #0f172a; }
    .muted { color: #94a3b8; font-size: 12px; }
    .summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 16px; }
    .card { border: 1px solid #1f2937; border-radius: 10px; padding: 12px; background: #111827; }
    .span { padding: 8px 10px; border-radius: 8px; margin-bottom: 6px; background: #0f172a; border: 1px solid #1f2937; }
    .ok { color: #22c55e; }
    .error { color: #ef4444; }
    .aborted { color: #f59e0b; }
    pre { white-space: pre-wrap; word-break: break-word; background: #020617; padding: 10px; border-radius: 8px; border: 1px solid #1f2937; }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
    .tab { padding: 6px 10px; border-radius: 999px; background: #111827; border: 1px solid #1f2937; cursor: pointer; }
    .tab.active { border-color: #60a5fa; color: #93c5fd; }
  </style>
</head>
<body>
  <div class="layout">
    <div class="panel">
      <h1>Sessions</h1>
      <div id="sessions"></div>
    </div>
    <div class="panel">
      <h2>Invocations</h2>
      <div id="invocations"></div>
    </div>
    <div class="panel">
      <h2>Trace</h2>
      <div class="tabs">
        <div class="tab active" data-tab="summary">Summary</div>
        <div class="tab" data-tab="spans">Spans</div>
        <div class="tab" data-tab="llm">LLM</div>
        <div class="tab" data-tab="tools">Tools</div>
      </div>
      <div id="content"></div>
    </div>
  </div>
  <script>
    const state = { sessions: [], invocations: [], invocation: null, tab: 'summary' };

    const statusClass = (status) => {
      if (!status) return '';
      const s = String(status).toLowerCase();
      if (s === 'ok') return 'ok';
      if (s === 'error') return 'error';
      if (s === 'aborted') return 'aborted';
      return '';
    };

    const formatDuration = (value) => {
      if (value === null || value === undefined || value === '') return '-';
      const ms = Number(value);
      if (!Number.isFinite(ms)) return String(value);
      if (ms < 1000) {
        if (ms >= 100) return `${ms.toFixed(0)}ms`;
        if (ms >= 10) return `${ms.toFixed(1)}ms`;
        return `${ms.toFixed(2)}ms`;
      }
      const seconds = ms / 1000;
      if (seconds < 60) {
        return `${seconds.toFixed(2)}s`;
      }
      const minutes = Math.floor(seconds / 60);
      const remainSeconds = seconds - minutes * 60;
      return `${minutes}m ${remainSeconds.toFixed(1)}s`;
    };

    async function fetchJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }

    function renderSessions() {
      const container = document.getElementById('sessions');
      container.innerHTML = state.sessions.map((session, idx) => `
        <div class="item ${idx === 0 ? 'active' : ''}" data-session="${session.session_id}">
          <div>${session.session_id}</div>
          <div class="muted">latest=${session.latest_time}</div>
          <div class="muted">invocations=${session.invocation_count} spans=${session.span_count}</div>
        </div>
      `).join('');
      container.querySelectorAll('[data-session]').forEach((el) => {
        el.onclick = async () => {
          container.querySelectorAll('.item').forEach((n) => n.classList.remove('active'));
          el.classList.add('active');
          await loadInvocations(el.dataset.session);
        };
      });
    }

    function renderInvocations() {
      const container = document.getElementById('invocations');
      container.innerHTML = state.invocations.map((inv, idx) => `
        <div class="item ${idx === 0 ? 'active' : ''}" data-invocation="${inv.invocation_id}">
          <div>${inv.invocation_id}</div>
          <div class="muted">start=${inv.start}</div>
          <div class="muted">duration=${inv.duration} spans=${inv.span_count}</div>
        </div>
      `).join('');
      container.querySelectorAll('[data-invocation]').forEach((el) => {
        el.onclick = async () => {
          container.querySelectorAll('.item').forEach((n) => n.classList.remove('active'));
          el.classList.add('active');
          await loadInvocation(el.dataset.invocation);
        };
      });
    }

    function renderContent() {
      const content = document.getElementById('content');
      if (!state.invocation) {
        content.innerHTML = '<div class="muted">No invocation selected.</div>';
        return;
      }

      const summary = state.invocation.summary;
      if (state.tab === 'summary') {
        content.innerHTML = `
          <div class="summary">
            <div class="card"><div class="muted">Session</div><div>${summary.session_id}</div></div>
            <div class="card"><div class="muted">Invocation</div><div>${summary.invocation_id}</div></div>
            <div class="card"><div class="muted">Trace</div><div>${summary.trace_id}</div></div>
            <div class="card"><div class="muted">Duration</div><div>${formatDuration(summary.duration_ms)}</div></div>
            <div class="card"><div class="muted">Start</div><div>${summary.start}</div></div>
            <div class="card"><div class="muted">Status</div><div class="${statusClass(summary.status)}">${summary.status}</div></div>
          </div>
        `;
        return;
      }

      if (state.tab === 'spans') {
        content.innerHTML = state.invocation.spans.map((span) => `
          <div class="span" style="margin-left:${span.depth * 18}px">
            <div><strong>${span.name}</strong> <span class="${statusClass(span.status)}">${span.status}</span></div>
            <div class="muted">duration=${formatDuration(span.duration_ms)}</div>
            <details>
              <summary>Attributes</summary>
              <pre>${JSON.stringify(span.attributes, null, 2)}</pre>
            </details>
          </div>
        `).join('');
        return;
      }

      if (state.tab === 'llm') {
        content.innerHTML = state.invocation.llm_calls.map((call) => `
          <div class="card" style="margin-bottom: 10px;">
            <div><strong>${call.model ?? '-'}</strong> <span class="muted">${call.provider ?? '-'}</span></div>
            <div class="muted">duration=${formatDuration(call.duration_ms)} ttft=${formatDuration(call.ttft_ms)} tpot=${formatDuration(call.tpot_ms)}</div>
            <div class="muted">tokens in=${call.input_tokens ?? '-'} out=${call.output_tokens ?? '-'}</div>
            <details>
              <summary>Output Preview</summary>
              <pre>${call.preview ?? '-'}</pre>
            </details>
          </div>
        `).join('') || '<div class="muted">No LLM calls.</div>';
        return;
      }

      if (state.tab === 'tools') {
        content.innerHTML = state.invocation.tool_calls.map((call) => `
          <div class="card" style="margin-bottom: 10px;">
            <div><strong>${call.name ?? '-'}</strong> <span class="${statusClass(call.status)}">${call.status ?? '-'}</span></div>
            <div class="muted">duration=${formatDuration(call.duration_ms)}</div>
            <details>
              <summary>Args</summary>
              <pre>${call.args ?? '-'}</pre>
            </details>
            <details>
              <summary>Result Preview</summary>
              <pre>${call.result_preview ?? '-'}</pre>
            </details>
          </div>
        `).join('') || '<div class="muted">No tool calls.</div>';
      }
    }

    async function loadSessions() {
      state.sessions = await fetchJson('/api/sessions');
      renderSessions();
      if (state.sessions.length > 0) {
        await loadInvocations(state.sessions[0].session_id);
      }
    }

    async function loadInvocations(sessionId) {
      state.invocations = await fetchJson(`/api/sessions/${sessionId}/invocations`);
      renderInvocations();
      if (state.invocations.length > 0) {
        await loadInvocation(state.invocations[0].invocation_id);
      } else {
        state.invocation = null;
        renderContent();
      }
    }

    async function loadInvocation(invocationId) {
      state.invocation = await fetchJson(`/api/invocations/${invocationId}`);
      renderContent();
    }

    document.querySelectorAll('.tab').forEach((tab) => {
      tab.onclick = () => {
        document.querySelectorAll('.tab').forEach((el) => el.classList.remove('active'));
        tab.classList.add('active');
        state.tab = tab.dataset.tab;
        renderContent();
      };
    });

    loadSessions().catch((err) => {
      document.getElementById('content').innerHTML = `<pre>${String(err)}</pre>`;
    });
  </script>
</body>
</html>"""


@click.group()
def telemetry() -> None:
    """Inspect local telemetry traces."""


@telemetry.command()
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
def info(config_path: str | None) -> None:
    """Show telemetry storage info."""
    config = _load_config(config_path)
    db_path = _telemetry_db_path(config)
    click.echo("Telemetry Info")
    _echo_kv("db_path", db_path)
    _echo_kv("exists", db_path.exists())
    if not db_path.exists():
        return

    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM spans").fetchone()
        _echo_kv("span_count", row["count"] if row else 0)
        _echo_kv("latest_session", _get_latest_session_id(conn) or "-")
        _echo_kv("latest_invocation", _get_latest_invocation_id(conn) or "-")
    finally:
        conn.close()


@telemetry.command()
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
def latest(config_path: str | None) -> None:
    """Show the latest invocation trace summary."""
    config = _load_config(config_path)
    conn = _connect(_telemetry_db_path(config))
    try:
        invocation_id = _get_latest_invocation_id(conn)
        if not invocation_id:
            raise click.ClickException("No invocation spans found in telemetry DB.")
        spans = _query_spans(conn, invocation_id=invocation_id)
        _print_invocation_summary(spans)
    finally:
        conn.close()


@telemetry.command()
@click.argument("invocation_id")
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
def invocation(invocation_id: str, config_path: str | None) -> None:
    """Show one invocation trace summary."""
    config = _load_config(config_path)
    conn = _connect(_telemetry_db_path(config))
    try:
        spans = _query_spans(conn, invocation_id=invocation_id)
        _print_invocation_summary(spans)
    finally:
        conn.close()


@telemetry.command()
@click.argument("session_id", required=False)
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
@click.option("--limit", type=int, default=10, show_default=True)
def session(session_id: str | None, config_path: str | None, limit: int) -> None:
    """List recent invocations in a session."""
    config = _load_config(config_path)
    conn = _connect(_telemetry_db_path(config))
    try:
        resolved_session_id = session_id or _get_latest_session_id(conn)
        if not resolved_session_id:
            raise click.ClickException("No session spans found in telemetry DB.")

        rows = conn.execute(
            """
            SELECT
              invocation_id,
              MIN(start_time_unix_nano) AS start_time_unix_nano,
              MAX(end_time_unix_nano) AS end_time_unix_nano,
              MAX(duration_ms) AS duration_ms,
              COUNT(*) AS span_count
            FROM spans
            WHERE session_id = ? AND invocation_id IS NOT NULL AND invocation_id != ''
            GROUP BY invocation_id
            ORDER BY start_time_unix_nano DESC
            LIMIT ?
            """,
            (resolved_session_id, limit),
        ).fetchall()

        click.echo(f"Session {resolved_session_id}")
        if not rows:
            click.echo("No invocation spans found.")
            return
        for row in rows:
            click.echo(
                "  ".join(
                    [
                        f"invocation={row['invocation_id']}",
                        f"start={_fmt_ts(row['start_time_unix_nano'])}",
                        f"dur={_fmt_ms(row['duration_ms'])}",
                        f"spans={row['span_count']}",
                    ]
                )
            )
    finally:
        conn.close()


@telemetry.command()
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
@click.option("--session-id", type=str)
@click.option("--invocation-id", type=str)
@click.option("--limit", type=int, default=20, show_default=True)
def spans(
    config_path: str | None,
    session_id: str | None,
    invocation_id: str | None,
    limit: int,
) -> None:
    """List raw spans with optional filters."""
    config = _load_config(config_path)
    conn = _connect(_telemetry_db_path(config))
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if invocation_id:
            clauses.append("invocation_id = ?")
            params.append(invocation_id)

        sql = """
        SELECT
          name,
          session_id,
          invocation_id,
          duration_ms,
          status_code,
          start_time_unix_nano
        FROM spans
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY start_time_unix_nano DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, tuple(params)).fetchall()
        if not rows:
            click.echo("No spans found.")
            return
        for row in rows:
            click.echo(
                "  ".join(
                    [
                        f"name={row['name']}",
                        f"session={row['session_id'] or '-'}",
                        f"invocation={row['invocation_id'] or '-'}",
                        f"dur={_fmt_ms(row['duration_ms'])}",
                        f"status={row['status_code'] or '-'}",
                        f"start={_fmt_ts(row['start_time_unix_nano'])}",
                    ]
                )
            )
    finally:
        conn.close()


@telemetry.command()
@click.option("-c", "--config", "config_path", type=click.Path(exists=True))
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=16853, type=int, show_default=True)
def serve(config_path: str | None, host: str, port: int) -> None:
    """Start a local telemetry viewer web service."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn

    config = _load_config(config_path)
    db_path = _telemetry_db_path(config)
    _connect(db_path).close()

    app = FastAPI(title="picho Telemetry Viewer")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _viewer_html()

    @app.get("/api/info")
    def api_info() -> JSONResponse:
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) AS count FROM spans").fetchone()
            payload = {
                "db_path": str(db_path),
                "span_count": row["count"] if row else 0,
                "latest_session": _get_latest_session_id(conn),
                "latest_invocation": _get_latest_invocation_id(conn),
            }
            return JSONResponse(payload)
        finally:
            conn.close()

    @app.get("/api/sessions")
    def api_sessions(limit: int = 100) -> JSONResponse:
        conn = _connect(db_path)
        try:
            return JSONResponse(_list_sessions(conn, limit))
        finally:
            conn.close()

    @app.get("/api/sessions/{session_id}/invocations")
    def api_session_invocations(session_id: str, limit: int = 100) -> JSONResponse:
        conn = _connect(db_path)
        try:
            return JSONResponse(
                _summarize_invocations_for_session(conn, session_id, limit)
            )
        finally:
            conn.close()

    @app.get("/api/invocations/{invocation_id}")
    def api_invocation(invocation_id: str) -> JSONResponse:
        conn = _connect(db_path)
        try:
            spans = _query_spans(conn, invocation_id=invocation_id)
            if not spans:
                raise HTTPException(status_code=404, detail="Invocation not found")
            return JSONResponse(_invocation_payload(spans))
        finally:
            conn.close()

    click.echo(f"Telemetry viewer: http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="warning")

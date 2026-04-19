"""
SQLite-backed exporter for local OpenTelemetry spans.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

_log = logging.getLogger("picho.observability")

_CREATE_SPANS_TABLE = """
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  kind TEXT,
  start_time_unix_nano INTEGER NOT NULL,
  end_time_unix_nano INTEGER NOT NULL,
  duration_ms REAL,
  status_code TEXT,
  status_description TEXT,
  session_id TEXT,
  invocation_id TEXT,
  attributes_json TEXT,
  events_json TEXT,
  resource_json TEXT,
  scope_name TEXT,
  scope_version TEXT
);
"""

_CREATE_TRACE_INDEX = """
CREATE INDEX IF NOT EXISTS spans_trace_id_idx ON spans(trace_id);
"""

_CREATE_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS spans_session_id_idx ON spans(session_id);
"""

_CREATE_INVOCATION_INDEX = """
CREATE INDEX IF NOT EXISTS spans_invocation_id_idx ON spans(invocation_id);
"""

_CREATE_START_TIME_INDEX = """
CREATE INDEX IF NOT EXISTS spans_start_time_idx ON spans(start_time_unix_nano);
"""

_INSERT_SPAN = """
INSERT OR REPLACE INTO spans (
  span_id,
  trace_id,
  parent_span_id,
  name,
  kind,
  start_time_unix_nano,
  end_time_unix_nano,
  duration_ms,
  status_code,
  status_description,
  session_id,
  invocation_id,
  attributes_json,
  events_json,
  resource_json,
  scope_name,
  scope_version
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _serialize_json(value: Any) -> str:
    try:
        return json.dumps(_json_safe(value), ensure_ascii=False)
    except Exception:
        return "{}"


class LocalSqliteSpanExporter(SpanExporter):
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._shutdown = False
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                timeout=30.0,
                check_same_thread=False,
            )
        return self._conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(_CREATE_SPANS_TABLE)
            conn.execute(_CREATE_TRACE_INDEX)
            conn.execute(_CREATE_SESSION_INDEX)
            conn.execute(_CREATE_INVOCATION_INDEX)
            conn.execute(_CREATE_START_TIME_INDEX)
            conn.commit()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            return SpanExportResult.SUCCESS

        try:
            rows: list[tuple[Any, ...]] = []
            for span in spans:
                attributes = dict(span.attributes) if span.attributes else {}
                session_id = attributes.get("gen_ai.conversation.id")
                invocation_id = attributes.get("picho.invocation.id")
                parent_span_id = (
                    f"{span.parent.span_id:016x}" if span.parent is not None else None
                )
                duration_ms = round((span.end_time - span.start_time) / 1_000_000, 3)
                events = [
                    {
                        "name": event.name,
                        "timestamp_unix_nano": event.timestamp,
                        "attributes": _json_safe(dict(event.attributes)),
                    }
                    for event in span.events
                ]
                rows.append(
                    (
                        f"{span.context.span_id:016x}",
                        f"{span.context.trace_id:032x}",
                        parent_span_id,
                        span.name,
                        span.kind.name,
                        span.start_time,
                        span.end_time,
                        duration_ms,
                        span.status.status_code.name,
                        span.status.description,
                        session_id,
                        invocation_id,
                        _serialize_json(attributes),
                        _serialize_json(events),
                        _serialize_json(dict(span.resource.attributes)),
                        span.instrumentation_scope.name,
                        span.instrumentation_scope.version,
                    )
                )

            with self._lock:
                conn = self._get_connection()
                conn.executemany(_INSERT_SPAN, rows)
                conn.commit()
            return SpanExportResult.SUCCESS
        except Exception as err:  # pragma: no cover - best effort exporter
            _log.warning("Local span export failed: %s", err)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._shutdown = True
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def force_flush(self, _timeout_millis: int = 30000) -> bool:
        return True

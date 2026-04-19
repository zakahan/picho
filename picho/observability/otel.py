"""
OpenTelemetry runtime setup and span helpers.
"""

from __future__ import annotations

import atexit
import logging
from contextlib import AbstractContextManager
from pathlib import Path
from threading import Lock
from typing import Any

from ..provider.types import Message, Usage
from .serialize import preview_json

_log = logging.getLogger("picho.observability")

try:  # pragma: no cover - import behavior depends on environment
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    from .exporter import LocalSqliteSpanExporter

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - import behavior depends on environment
    trace = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    Status = None
    StatusCode = None
    LocalSqliteSpanExporter = None
    _OTEL_AVAILABLE = False

_INSTALL_HINT = (
    "Install OpenTelemetry in the active Python environment: "
    "`pip install opentelemetry-api opentelemetry-sdk` "
    "or disable it with config `observability.enabled = false`."
)

_CONFIG_LOCK = Lock()
_CONFIGURED = False
_CONFIGURED_PATH: Path | None = None
_PROVIDER: Any = None


class _NoopSpan:
    def is_recording(self) -> bool:
        return False

    def set_attribute(self, _key: str, _value: Any) -> None:
        return None

    def set_attributes(self, _attributes: dict[str, Any]) -> None:
        return None

    def add_event(self, _name: str, _attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, _error: BaseException) -> None:
        return None

    def set_status(self, _status: Any) -> None:
        return None


class _NoopSpanContext(AbstractContextManager):
    def __enter__(self) -> _NoopSpan:
        return _NoopSpan()

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(
        self,
        _name: str,
        _attributes: dict[str, Any] | None = None,
    ) -> _NoopSpanContext:
        return _NoopSpanContext()


def _sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    if not attributes:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            sanitized[key] = value
        elif isinstance(value, (list, tuple)):
            if all(isinstance(item, (bool, int, float, str)) for item in value):
                sanitized[key] = list(value)
            else:
                sanitized[key] = preview_json(value)
        else:
            sanitized[key] = preview_json(value)
    return sanitized


def _build_resource() -> Any:
    service_version = "unknown"
    try:
        from importlib.metadata import version

        service_version = version("picho")
    except Exception:
        pass

    return Resource.create(
        {
            "service.name": "picho",
            "service.version": service_version,
        }
    )


def is_observability_enabled() -> bool:
    return _CONFIGURED and _OTEL_AVAILABLE


def configure_observability(telemetry_dir: str | Path) -> None:
    global _CONFIGURED, _CONFIGURED_PATH, _PROVIDER

    if not _OTEL_AVAILABLE:
        _log.warning(
            "OpenTelemetry is not available; observability is disabled. %s",
            _INSTALL_HINT,
        )
        return

    target_dir = Path(telemetry_dir)
    with _CONFIG_LOCK:
        if _CONFIGURED:
            if _CONFIGURED_PATH and _CONFIGURED_PATH != target_dir:
                _log.warning(
                    "Observability already configured at %s; ignoring %s",
                    _CONFIGURED_PATH,
                    target_dir,
                )
            return

        spans_db = target_dir / "spans.db"
        provider = TracerProvider(resource=_build_resource())
        processor = BatchSpanProcessor(
            LocalSqliteSpanExporter(spans_db),
            max_queue_size=2048,
            max_export_batch_size=256,
            schedule_delay_millis=500,
            export_timeout_millis=2000,
        )
        provider.add_span_processor(processor)

        try:
            trace.set_tracer_provider(provider)
        except Exception as err:  # pragma: no cover - best effort setup
            _log.warning("Failed to configure OpenTelemetry provider: %s", err)
            return

        _PROVIDER = provider
        _CONFIGURED = True
        _CONFIGURED_PATH = target_dir
        _log.info("Observability configured | path=%s", spans_db)


def shutdown_observability() -> None:
    global _CONFIGURED, _PROVIDER

    with _CONFIG_LOCK:
        provider = _PROVIDER
        _PROVIDER = None
        _CONFIGURED = False

    if provider is None:
        return

    try:  # pragma: no cover - shutdown timing is environment-specific
        provider.force_flush()
        provider.shutdown()
    except Exception as err:
        _log.warning("Observability shutdown failed: %s", err)


atexit.register(shutdown_observability)


def get_tracer(name: str) -> Any:
    if not _OTEL_AVAILABLE:
        return _NoopTracer()
    return trace.get_tracer(name)


def set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if not attributes or not hasattr(span, "set_attributes"):
        return
    sanitized = _sanitize_attributes(attributes)
    if not sanitized:
        return
    span.set_attributes(sanitized)


def add_event(span: Any, name: str, attributes: dict[str, Any] | None = None) -> None:
    if not hasattr(span, "add_event"):
        return
    span.add_event(name, _sanitize_attributes(attributes))


def record_exception(span: Any, error: BaseException) -> None:
    if hasattr(span, "record_exception"):
        span.record_exception(error)
    if hasattr(span, "set_status") and Status is not None and StatusCode is not None:
        span.set_status(Status(StatusCode.ERROR, str(error)))


def set_ok_status(span: Any) -> None:
    if hasattr(span, "set_status") and Status is not None and StatusCode is not None:
        span.set_status(Status(StatusCode.OK))


def set_usage_attributes(span: Any, usage: Usage | None) -> None:
    if usage is None:
        return
    set_span_attributes(
        span,
        {
            "gen_ai.usage.input_tokens": usage.input_tokens,
            "gen_ai.usage.output_tokens": usage.output_tokens,
            "picho.usage.cache_read_tokens": usage.cache_read,
            "picho.usage.cache_write_tokens": usage.cache_write,
            "picho.usage.total_tokens": usage.total_tokens,
        },
    )


def set_message_attributes(span: Any, prefix: str, message: Message | None) -> None:
    if message is None:
        return
    set_span_attributes(
        span,
        {
            f"{prefix}.role": getattr(message, "role", type(message).__name__),
            f"{prefix}.preview": preview_json(message),
        },
    )

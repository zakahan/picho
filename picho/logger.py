"""
Logging module for picho.

Provides centralized logging configuration, structured runtime context, and
exception formatting helpers so runtime failures remain visible to both logs
and the CLI.
"""

from __future__ import annotations

import logging
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TextIO


_default_log_dir: Path | None = None
_log_context: ContextVar[dict[str, str]] = ContextVar("picho_log_context", default={})


def _stringify_context_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _shorten(value: str, length: int = 8) -> str:
    if not value:
        return "-"
    return value[:length]


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get({})
        session_id = context.get("session_id", "")
        invocation_id = context.get("invocation_id", "")
        record.session_id = session_id or "-"
        record.session_short = _shorten(session_id)
        record.invocation_id = invocation_id or "-"
        record.invocation_short = _shorten(invocation_id)
        record.workspace = context.get("workspace", "-") or "-"
        record.session_file = context.get("session_file", "-") or "-"
        return True


def get_log_context() -> dict[str, str]:
    return dict(_log_context.get({}))


def set_log_context(**context: Any) -> Token:
    current = get_log_context()
    merged = {**current}
    for key, value in context.items():
        if value is None:
            merged.pop(key, None)
            continue
        merged[key] = _stringify_context_value(value)
    return _log_context.set(merged)


def reset_log_context(token: Token) -> None:
    _log_context.reset(token)


@contextmanager
def log_context(**context: Any) -> Iterator[None]:
    token = set_log_context(**context)
    try:
        yield
    finally:
        reset_log_context(token)


def format_exception(error: BaseException) -> str:
    formatted = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).strip()
    if formatted:
        return formatted

    error_type = type(error).__name__
    message = str(error).strip()
    return f"{error_type}: {message}" if message else error_type


def _format_extra_context(extra_context: dict[str, Any]) -> str:
    parts = []
    for key, value in extra_context.items():
        if value is None:
            continue
        text = _stringify_context_value(value)
        if not text:
            continue
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_exception(
    logger: logging.Logger,
    message: str,
    error: BaseException,
    *,
    level: int = logging.ERROR,
    **extra_context: Any,
) -> None:
    context_text = _format_extra_context(extra_context)
    prefix = f"{message} | {context_text}" if context_text else message
    logger.log(level, "%s\n%s", prefix, format_exception(error))


def set_log_dir(log_dir: str | Path) -> None:
    global _default_log_dir
    _default_log_dir = Path(log_dir)


def get_log_dir() -> Path:
    if _default_log_dir:
        return _default_log_dir
    cwd = Path.cwd()
    return cwd / ".picho" / "logs"


def setup_logger(
    name: str = "picho",
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    stream: TextIO | None = sys.stderr,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "sid=%(session_short)s | inv=%(invocation_short)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = _ContextFilter()

    if stream:
        handler = logging.StreamHandler(stream)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        logger.addHandler(handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "picho") -> logging.Logger:
    return logging.getLogger(name)


_default_logger: logging.Logger | None = None


def init_logging(
    level: int = logging.INFO,
    log_to_file: bool = True,
    stream: TextIO | None = sys.stderr,
) -> logging.Logger:
    global _default_logger

    log_file = None
    if log_to_file:
        log_dir = get_log_dir()
        log_file = log_dir / f"picho-{datetime.now().strftime('%Y%m%d')}.log"

    _default_logger = setup_logger(
        name="picho",
        level=level,
        log_file=log_file,
        stream=stream,
    )

    return _default_logger


def log() -> logging.Logger:
    global _default_logger
    if _default_logger is None:
        _default_logger = setup_logger(name="picho")
    return _default_logger

"""Raw model request session logging for debugging provider payloads."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import CURRENT_SESSION_VERSION
from ..logger import get_logger

_log = get_logger(__name__)


class RawSessionWriter:
    def __init__(self, session_file: str, raw_session_dir: str):
        self.session_file = session_file
        self.raw_session_dir = raw_session_dir
        self.raw_session_file = str(
            Path(raw_session_dir) / f"{Path(session_file).stem}.json"
        )
        os.makedirs(raw_session_dir, exist_ok=True)

    def write_model_request(
        self,
        *,
        session_id: str,
        invocation_id: str,
        provider: str,
        model: str,
        payload: dict[str, Any],
    ) -> None:
        snapshot = {
            "type": "raw_session_snapshot",
            "version": CURRENT_SESSION_VERSION,
            "updated_at": _timestamp(),
            "session_file": self.session_file,
            "request": {
                "session_id": session_id,
                "invocation_id": invocation_id,
                "provider": provider,
                "model": model,
            },
            "payload": _sanitize_payload(payload),
        }

        with open(self.raw_session_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            f.write("\n")

        _log.debug(
            "Raw model request snapshot written: "
            f"session_id={session_id} file={self.raw_session_file}"
        )


def raw_session_dir_for_sessions_path(sessions_path: str) -> str:
    return str(Path(sessions_path).parent / "raw_session")


def _timestamp() -> str:
    return datetime.now().isoformat()


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _to_jsonable(payload)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {
                "api_key",
                "apikey",
                "authorization",
                "headers",
                "extra_headers",
            }:
                continue
            sanitized[str(key)] = _to_jsonable(item)
        return sanitized

    if isinstance(value, list | tuple):
        return [_to_jsonable(item) for item in value]

    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))

    if hasattr(value, "to_dict"):
        try:
            return _to_jsonable(value.to_dict())
        except Exception:
            pass

    if hasattr(value, "model_dump"):
        try:
            return _to_jsonable(value.model_dump())
        except Exception:
            pass

    if value is None or isinstance(value, str | int | float | bool):
        return value

    return repr(value)

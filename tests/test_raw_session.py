from __future__ import annotations

import asyncio
import json
from pathlib import Path

from picho.runner import Runner
from picho.session.raw import RawSessionWriter


def _runner_config(tmp_path: Path) -> dict:
    return {
        "path": {
            "base": str(tmp_path / ".picho"),
            "logs": str(tmp_path / "logs"),
            "sessions": str(tmp_path / "sessions"),
            "executor": str(tmp_path),
            "cache": str(tmp_path / "cache"),
            "skills": [],
        },
        "agent": {
            "model": {
                "model_provider": "mock",
                "model_name": "mock-model",
                "input_types": ["text"],
            },
            "builtin": {
                "tool": [],
                "skill": [],
            },
        },
        "session_manager": {
            "persist": True,
        },
        "debug": {
            "raw_session": True,
        },
    }


def test_runner_writes_raw_session_payload_next_to_sessions(tmp_path: Path):
    runner = Runner(config_type="dict", config=_runner_config(tmp_path))
    session_id = runner.create_session()
    state = runner.get_session(session_id)
    assert state is not None

    asyncio.run(runner.prompt(session_id, "hello raw"))
    asyncio.run(runner.prompt(session_id, "latest only"))

    session_file = Path(state.session.get_session_file())
    raw_file = tmp_path / "raw_session" / f"{session_file.stem}.json"
    assert raw_file.exists()

    request = json.loads(raw_file.read_text())
    assert request["type"] == "raw_session_snapshot"
    assert request["session_file"] == str(session_file)
    assert request["request"]["session_id"] == session_id
    assert request["request"]["provider"] == "mock"
    assert request["request"]["model"] == "mock-model"
    assert request["payload"]["model"] == "mock-model"
    assert request["payload"]["messages"][-1]["content"][0]["text"] == "latest only"
    assert "\n  " in raw_file.read_text()


def test_raw_session_writer_sanitizes_credentials_and_headers(tmp_path: Path):
    session_file = str(tmp_path / "sessions" / "session_abc123.jsonl")
    raw_dir = str(tmp_path / "raw_session")
    writer = RawSessionWriter(session_file=session_file, raw_session_dir=raw_dir)

    writer.write_model_request(
        session_id="abc123",
        invocation_id="invoke123",
        provider="provider",
        model="model",
        payload={
            "model": "model",
            "api_key": "secret",
            "headers": {"Authorization": "Bearer secret"},
            "extra_headers": {"x-secret": "secret"},
            "nested": {"authorization": "Bearer secret", "text": "visible"},
        },
    )

    snapshot = json.loads(Path(writer.raw_session_file).read_text())
    payload = snapshot["payload"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret" not in serialized
    assert payload == {"model": "model", "nested": {"text": "visible"}}

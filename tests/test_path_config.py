from __future__ import annotations

from pathlib import Path

from picho.config import Config
from picho.runner import Runner


def _mock_agent_config() -> dict:
    return {
        "model": {
            "model_provider": "mock",
            "model_name": "mock-model",
            "input_types": ["text"],
        },
        "builtin": {
            "tool": [],
            "skill": [],
        },
    }


def test_default_path_base_is_picho_dir_and_executor_is_cwd(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    config = Config.from_dict({})

    assert config.path.base == str(tmp_path / ".picho")
    assert config.path.logs_path == str(tmp_path / ".picho" / "logs")
    assert config.path.sessions_path == str(tmp_path / ".picho" / "sessions")
    assert config.path.telemetry_path == str(tmp_path / ".picho" / "telemetry")
    assert config.path.cache_path == str(tmp_path / ".picho" / "caches")
    assert config.path.executor_path == str(tmp_path)
    assert config.path.get_skill_paths() == [str(tmp_path / ".picho" / "skills")]


def test_runner_uses_base_for_state_dirs_and_cwd_for_default_workspace(
    tmp_path: Path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_base = tmp_path / "state"
    monkeypatch.chdir(workspace)

    runner = Runner(
        config_type="dict",
        config={
            "path": {
                "base": str(state_base),
                "skills": [],
            },
            "agent": _mock_agent_config(),
            "observability": {
                "enabled": False,
            },
        },
    )

    session_id = runner.create_session()
    state = runner.get_session(session_id)

    assert state is not None
    assert state.workspace == str(workspace)
    assert Path(state.session.get_session_file()).parent == state_base / "sessions"


def test_explicit_state_paths_are_used_as_final_paths(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    logs = tmp_path / "logx"
    sessions = tmp_path / "sessionx"
    telemetry = tmp_path / "telemetryx"
    caches = tmp_path / "cachex"

    config = Config.from_dict(
        {
            "path": {
                "logs": str(logs),
                "sessions": str(sessions),
                "telemetry": str(telemetry),
                "cache": str(caches),
            }
        }
    )

    assert config.path.logs_path == str(logs)
    assert config.path.sessions_path == str(sessions)
    assert config.path.telemetry_path == str(telemetry)
    assert config.path.cache_path == str(caches)


def test_legacy_session_manager_cwd_maps_to_state_base_and_executor(tmp_path: Path):
    config = Config.from_dict({"session_manager": {"cwd": str(tmp_path)}})

    assert config.path.base == str(tmp_path / ".picho")
    assert config.path.sessions_path == str(tmp_path / ".picho" / "sessions")
    assert config.path.executor_path == str(tmp_path)

from __future__ import annotations

from pathlib import Path

from picho.runner import Runner


def test_runner_create_session_without_api_key_uses_mock_provider(tmp_path: Path):
    config = {
        "path": {
            "base": str(tmp_path),
            "logs": str(tmp_path),
            "sessions": str(tmp_path),
            "executor": str(tmp_path),
            "cache": str(tmp_path),
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
                "tool_config": {
                    "read": {
                        "extensions": [],
                        "video_compression": {
                            "enabled": True,
                            "trigger_size_mb": 512,
                        },
                    }
                },
            },
        },
        "session_manager": {
            "persist": True,
        },
    }

    runner = Runner(config_type="dict", config=config)
    session_id = runner.create_session()
    state = runner.get_session(session_id)

    assert runner.has_session(session_id) is True
    assert state is not None
    assert state.agent.state.model is not None
    assert state.agent.state.model.model_provider == "mock"

    session_file = state.session.get_session_file()
    assert session_file is not None
    assert Path(session_file).exists()

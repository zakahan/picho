from __future__ import annotations

from pathlib import Path

import pytest

from picho.config import AgentConfig, Config
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


def _runner_config(tmp_path: Path, **agent_overrides) -> dict:
    agent = _mock_agent_config()
    agent.update(agent_overrides)
    return {
        "path": {
            "base": str(tmp_path),
            "logs": str(tmp_path),
            "sessions": str(tmp_path),
            "executor": str(tmp_path),
            "cache": str(tmp_path / "cache"),
            "skills": [],
        },
        "agent": agent,
        "observability": {"enabled": False},
    }


class TestAgentConfigInstructionsFiles:
    def test_instructions_files_parsed_from_dict(self):
        cfg = AgentConfig.from_dict({"instructions_files": ["a.md", "b.md"]})
        assert cfg.instructions == ""
        assert cfg.instructions_files == ["a.md", "b.md"]

    def test_instructions_default_when_neither_set(self):
        cfg = AgentConfig.from_dict({})
        assert cfg.instructions == "You are a helpful AI assistant named picho."
        assert cfg.instructions_files == []

    def test_instructions_used_when_set(self):
        cfg = AgentConfig.from_dict({"instructions": "Be concise."})
        assert cfg.instructions == "Be concise."
        assert cfg.instructions_files == []

    def test_mutual_exclusivity_raises(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            AgentConfig.from_dict(
                {
                    "instructions": "Be concise.",
                    "instructions_files": ["a.md"],
                }
            )

    def test_none_data_returns_defaults(self):
        cfg = AgentConfig.from_dict(None)
        assert cfg.instructions == "You are a helpful AI assistant named picho."
        assert cfg.instructions_files == []

    def test_config_from_dict_propagates_instructions_files(self):
        config = Config.from_dict(
            {
                "agent": {
                    "instructions_files": ["x.md"],
                }
            }
        )
        assert config.agent.instructions == ""
        assert config.agent.instructions_files == ["x.md"]


class TestRunnerInstructionsFiles:
    def test_instructions_files_are_read_and_concatenated(self, tmp_path: Path):
        instructions_dir = tmp_path / "instructions"
        instructions_dir.mkdir()
        (instructions_dir / "base.md").write_text("You are picho.", encoding="utf-8")
        (instructions_dir / "style.md").write_text(
            "Be concise and helpful.", encoding="utf-8"
        )

        runner = Runner(
            config_type="dict",
            config=_runner_config(
                tmp_path,
                instructions_files=[
                    "instructions/base.md",
                    "instructions/style.md",
                ],
            ),
        )

        session_id = runner.create_session()
        agent = runner.get_agent(session_id)
        assert agent is not None

        expected = "You are picho.\n\nBe concise and helpful."
        assert agent.state.instructions.startswith(expected)

    def test_instructions_files_absolute_path(self, tmp_path: Path):
        abs_file = tmp_path / "abs_instructions.md"
        abs_file.write_text("Absolute instructions.", encoding="utf-8")

        runner = Runner(
            config_type="dict",
            config=_runner_config(
                tmp_path,
                instructions_files=[str(abs_file)],
            ),
        )

        session_id = runner.create_session()
        agent = runner.get_agent(session_id)
        assert "Absolute instructions." in agent.state.instructions

    def test_instructions_file_not_found_raises(self, tmp_path: Path):
        runner = Runner(
            config_type="dict",
            config=_runner_config(
                tmp_path,
                instructions_files=["nonexistent.md"],
            ),
        )
        with pytest.raises(FileNotFoundError, match="instructions file not found"):
            runner.create_session()

    def test_instructions_string_still_works(self, tmp_path: Path):
        runner = Runner(
            config_type="dict",
            config=_runner_config(
                tmp_path,
                instructions="You are a test assistant.",
            ),
        )

        session_id = runner.create_session()
        agent = runner.get_agent(session_id)
        assert "You are a test assistant." in agent.state.instructions

    def test_default_instructions_when_neither_set(self, tmp_path: Path):
        runner = Runner(
            config_type="dict",
            config=_runner_config(tmp_path),
        )

        session_id = runner.create_session()
        agent = runner.get_agent(session_id)
        assert "You are a helpful AI assistant named picho." in agent.state.instructions

    def test_mutual_exclusivity_raises_at_config_level(self, tmp_path: Path):
        with pytest.raises(ValueError, match="mutually exclusive"):
            Runner(
                config_type="dict",
                config=_runner_config(
                    tmp_path,
                    instructions="Hello",
                    instructions_files=["a.md"],
                ),
            )

    def test_single_instructions_file(self, tmp_path: Path):
        single = tmp_path / "single.md"
        single.write_text("Single file instructions.", encoding="utf-8")

        runner = Runner(
            config_type="dict",
            config=_runner_config(
                tmp_path,
                instructions_files=["single.md"],
            ),
        )

        session_id = runner.create_session()
        agent = runner.get_agent(session_id)
        assert "Single file instructions." in agent.state.instructions

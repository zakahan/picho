"""
Skill types for picho
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


@dataclass
class SkillFrontmatter:
    """
    YAML frontmatter structure for skill files.

    Example:
    ---
    name: planner
    description: Creates implementation plans
    tools: read, grep, find
    model: claude-sonnet-4-5
    disable-model-invocation: false
    ---
    """

    name: str = ""
    description: str = ""
    tools: list[str] = field(default_factory=list)
    model: str = ""
    disable_model_invocation: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillFrontmatter":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            tools=_parse_tools(d.get("tools")),
            model=d.get("model", ""),
            disable_model_invocation=d.get("disable-model-invocation", False),
            extra={
                k: v
                for k, v in d.items()
                if k
                not in {
                    "name",
                    "description",
                    "tools",
                    "model",
                    "disable-model-invocation",
                }
            },
        )


def _parse_tools(tools: Any) -> list[str]:
    if tools is None:
        return []
    if isinstance(tools, str):
        return [t.strip() for t in tools.split(",") if t.strip()]
    if isinstance(tools, list):
        return [str(t).strip() for t in tools if t]
    return []


@dataclass
class Skill:
    """
    A loaded skill with metadata and content.
    """

    name: str
    description: str
    file_path: str
    base_dir: str
    source: str
    content: str = ""
    tools: list[str] = field(default_factory=list)
    model: str = ""
    disable_model_invocation: bool = False


@dataclass
class Diagnostic:
    """
    Diagnostic message for skill loading.
    """

    type: Literal["error", "warning", "info"]
    message: str
    path: str = ""


@dataclass
class LoadSkillsResult:
    """
    Result of loading skills from directories.
    """

    skills: list[Skill] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

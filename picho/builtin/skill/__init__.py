"""
Built-in skills for picho
"""

from picho.skills.loader import load_skills_from_dir

__all__ = [
    "get_builtin_skills_dir",
    "load_builtin_skills",
]


def get_builtin_skills_dir() -> str:
    """Get the path to the built-in skills directory."""
    import os

    return os.path.dirname(__file__)


def load_builtin_skills(skill_names: list[str] | None = None) -> "LoadSkillsResult":
    """
    Load built-in skills.

    Args:
        skill_names: Optional list of skill names to load. If None, loads all.

    Returns:
        LoadSkillsResult with skills and diagnostics
    """
    from picho.skills.types import LoadSkillsResult

    builtin_dir = get_builtin_skills_dir()
    result = load_skills_from_dir(builtin_dir, "builtin")

    if skill_names:
        result.skills = [s for s in result.skills if s.name in skill_names]

    return result

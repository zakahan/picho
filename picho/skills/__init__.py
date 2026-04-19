"""
Skills module for picho

Skills are markdown files with YAML frontmatter that provide
specialized instructions for specific tasks.
"""

from .types import Skill, SkillFrontmatter, LoadSkillsResult, Diagnostic
from .frontmatter import parse_frontmatter, strip_frontmatter
from .loader import load_skills, load_skills_from_dir, format_skills_for_prompt

__all__ = [
    "Skill",
    "SkillFrontmatter",
    "LoadSkillsResult",
    "Diagnostic",
    "parse_frontmatter",
    "strip_frontmatter",
    "load_skills",
    "load_skills_from_dir",
    "format_skills_for_prompt",
]

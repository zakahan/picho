from __future__ import annotations

from pathlib import Path

from picho.skills.frontmatter import parse_frontmatter, strip_frontmatter
from picho.skills.loader import (
    format_skills_for_prompt,
    load_skills,
    load_skills_from_dir,
)
from picho.skills.types import Skill


def test_parse_frontmatter_and_strip_body():
    content = """---
name: sample-skill
description: Sample description
tools: read, write
---
Skill body here
"""

    frontmatter, body = parse_frontmatter(content)

    assert frontmatter["name"] == "sample-skill"
    assert frontmatter["description"] == "Sample description"
    assert frontmatter["tools"] == "read, write"
    assert body == "Skill body here"
    assert strip_frontmatter(content) == "Skill body here"


def test_load_skills_from_dir_loads_skill_subdirectory(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: sample-skill
description: Sample skill
tools: read, write
---
Use this skill when the task needs sample handling.
""",
        encoding="utf-8",
    )

    result = load_skills_from_dir(str(skills_root), "config")

    assert len(result.skills) == 1
    assert result.diagnostics == []
    skill = result.skills[0]
    assert skill.name == "sample-skill"
    assert skill.description == "Sample skill"
    assert skill.tools == ["read", "write"]
    assert skill.content == "Use this skill when the task needs sample handling."


def test_load_skills_reports_duplicate_name_and_missing_path(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    missing_root = tmp_path / "missing"

    for root in (first_root, second_root):
        skill_dir = root / "dup-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: dup-skill
description: Duplicate skill
---
Body
""",
            encoding="utf-8",
        )

    result = load_skills(
        cwd=str(tmp_path),
        skill_paths=[str(first_root), str(second_root), str(missing_root)],
        include_defaults=False,
    )

    assert len(result.skills) == 1
    messages = [diag.message for diag in result.diagnostics]
    assert any('duplicate skill name "dup-skill"' in message for message in messages)
    assert any("skill path does not exist" in message for message in messages)


def test_format_skills_for_prompt_skips_disabled_and_escapes_xml(tmp_path: Path):
    visible_skill = Skill(
        name="visible-skill",
        description='Use <tag> & "quotes"',
        file_path=str(tmp_path / "visible.md"),
        base_dir=str(tmp_path),
        source="config",
        content="visible",
    )
    hidden_skill = Skill(
        name="hidden-skill",
        description="Should be hidden",
        file_path=str(tmp_path / "hidden.md"),
        base_dir=str(tmp_path),
        source="config",
        content="hidden",
        disable_model_invocation=True,
    )

    prompt = format_skills_for_prompt([visible_skill, hidden_skill])

    assert "visible-skill" in prompt
    assert "hidden-skill" not in prompt
    assert "Use &lt;tag&gt; &amp; &quot;quotes&quot;" in prompt

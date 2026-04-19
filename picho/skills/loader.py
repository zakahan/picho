"""
Skill loader for picho

Discovers and loads skills from directories following the Agent Skills spec.
Skills are markdown files with YAML frontmatter.

Discovery rules:
- If a directory contains SKILL.md, treat it as a skill root and do not recurse further
- Otherwise, load direct .md children in the root
- Recurse into subdirectories to find SKILL.md
"""

from __future__ import annotations

import os
import re

from .types import (
    Skill,
    SkillFrontmatter,
    LoadSkillsResult,
    Diagnostic,
    MAX_NAME_LENGTH,
    MAX_DESCRIPTION_LENGTH,
)
from .frontmatter import parse_frontmatter


IGNORE_FILE_NAMES = [".gitignore", ".ignore", ".fdignore"]


def _validate_name(name: str, parent_dir_name: str) -> list[str]:
    """
    Validate skill name per Agent Skills spec.
    Returns list of error messages (empty if valid).
    """
    errors = []

    if name != parent_dir_name:
        errors.append(
            f'name "{name}" does not match parent directory "{parent_dir_name}"'
        )

    if len(name) > MAX_NAME_LENGTH:
        errors.append(f"name exceeds {MAX_NAME_LENGTH} characters ({len(name)})")

    if not re.match(r"^[a-z0-9-]+$", name):
        errors.append(
            "name contains invalid characters (must be lowercase a-z, 0-9, hyphens only)"
        )

    if name.startswith("-") or name.endswith("-"):
        errors.append("name must not start or end with a hyphen")

    if "--" in name:
        errors.append("name must not contain consecutive hyphens")

    return errors


def _validate_description(description: str | None) -> list[str]:
    """
    Validate description per Agent Skills spec.
    """
    errors = []

    if not description or not description.strip():
        errors.append("description is required")
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"description exceeds {MAX_DESCRIPTION_LENGTH} characters ({len(description)})"
        )

    return errors


def _escape_xml(s: str) -> str:
    """Escape XML special characters."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _load_ignore_patterns(dir_path: str, root_dir: str) -> list[str]:
    """
    Load ignore patterns from .gitignore/.ignore/.fdignore files.
    Returns patterns prefixed with relative path from root.
    """
    patterns = []
    rel_dir = os.path.relpath(dir_path, root_dir)
    prefix = rel_dir.replace(os.sep, "/") + "/" if rel_dir != "." else ""

    for filename in IGNORE_FILE_NAMES:
        ignore_path = os.path.join(dir_path, filename)
        if not os.path.exists(ignore_path):
            continue

        try:
            with open(ignore_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n\r")
                    pattern = _prefix_ignore_pattern(line, prefix)
                    if pattern:
                        patterns.append(pattern)
        except Exception:
            pass

    return patterns


def _prefix_ignore_pattern(line: str, prefix: str) -> str | None:
    """
    Prefix an ignore pattern with the relative directory path.
    """
    trimmed = line.strip()
    if not trimmed:
        return None
    if trimmed.startswith("#") and not trimmed.startswith("\\#"):
        return None

    pattern = line
    negated = False

    if pattern.startswith("!"):
        negated = True
        pattern = pattern[1:]
    elif pattern.startswith("\\!"):
        pattern = pattern[1:]

    if pattern.startswith("/"):
        pattern = pattern[1:]

    prefixed = f"{prefix}{pattern}" if prefix else pattern
    return f"!{prefixed}" if negated else prefixed


def _matches_ignore(path: str, patterns: list[str]) -> bool:
    """
    Check if a path matches any ignore pattern.
    Simple implementation - supports basic glob patterns.
    """
    import fnmatch

    for pattern in patterns:
        if pattern.startswith("!"):
            if fnmatch.fnmatch(path, pattern[1:]):
                return False
        else:
            if fnmatch.fnmatch(path, pattern):
                return True
            if fnmatch.fnmatch(path, pattern.rstrip("/") + "/*"):
                return True

    return False


def _load_skill_from_file(
    file_path: str,
    source: str,
) -> tuple[Skill | None, list[Diagnostic]]:
    """
    Load a single skill from a markdown file.
    """
    diagnostics = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        frontmatter_dict, body = parse_frontmatter(raw_content)
        frontmatter = SkillFrontmatter.from_dict(frontmatter_dict)

        skill_dir = os.path.dirname(file_path)
        parent_dir_name = os.path.basename(skill_dir)

        desc_errors = _validate_description(frontmatter.description)
        for error in desc_errors:
            diagnostics.append(
                Diagnostic(type="warning", message=error, path=file_path)
            )

        name = frontmatter.name or parent_dir_name

        name_errors = _validate_name(name, parent_dir_name)
        for error in name_errors:
            diagnostics.append(
                Diagnostic(type="warning", message=error, path=file_path)
            )

        if not frontmatter.description or not frontmatter.description.strip():
            return None, diagnostics

        return Skill(
            name=name,
            description=frontmatter.description,
            file_path=file_path,
            base_dir=skill_dir,
            source=source,
            content=body,
            tools=frontmatter.tools,
            model=frontmatter.model,
            disable_model_invocation=frontmatter.disable_model_invocation,
        ), diagnostics

    except Exception as e:
        message = str(e) if e else "failed to parse skill file"
        diagnostics.append(Diagnostic(type="warning", message=message, path=file_path))
        return None, diagnostics


def load_skills_from_dir(
    dir_path: str,
    source: str,
    ignore_patterns: list[str] | None = None,
    root_dir: str | None = None,
    include_root_files: bool = True,
) -> LoadSkillsResult:
    """
    Load skills from a directory.

    Discovery rules:
    - If SKILL.md exists in a directory, load it and don't recurse
    - Otherwise, scan subdirectories for SKILL.md
    - Root .md files are loaded if include_root_files is True
    """
    skills = []
    diagnostics = []

    if not os.path.exists(dir_path):
        return LoadSkillsResult(skills, diagnostics)

    root = root_dir or dir_path
    patterns = list(ignore_patterns) if ignore_patterns else []
    patterns.extend(_load_ignore_patterns(dir_path, root))

    try:
        entries = list(os.scandir(dir_path))
    except Exception:
        return LoadSkillsResult(skills, diagnostics)

    for entry in entries:
        if entry.name == "SKILL.md":
            full_path = entry.path

            if entry.is_symlink():
                try:
                    full_path = os.path.realpath(entry.path)
                    if not os.path.isfile(full_path):
                        continue
                except Exception:
                    continue
            elif not entry.is_file():
                continue

            rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
            if _matches_ignore(rel_path, patterns):
                continue

            skill, skill_diags = _load_skill_from_file(full_path, source)
            if skill:
                skills.append(skill)
            diagnostics.extend(skill_diags)

            return LoadSkillsResult(skills, diagnostics)

    for entry in entries:
        if entry.name.startswith("."):
            continue

        if entry.name == "node_modules":
            continue

        full_path = entry.path
        is_dir = entry.is_dir()
        is_file = entry.is_file()

        if entry.is_symlink():
            try:
                real_path = os.path.realpath(full_path)
                is_dir = os.path.isdir(real_path)
                is_file = os.path.isfile(real_path)
            except Exception:
                continue

        rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
        ignore_path = f"{rel_path}/" if is_dir else rel_path

        if _matches_ignore(ignore_path, patterns):
            continue

        if is_dir:
            sub_result = load_skills_from_dir(
                full_path,
                source,
                patterns,
                root,
                include_root_files=False,
            )
            skills.extend(sub_result.skills)
            diagnostics.extend(sub_result.diagnostics)
            continue

        if not is_file or not include_root_files or not entry.name.endswith(".md"):
            continue

        skill, skill_diags = _load_skill_from_file(full_path, source)
        if skill:
            skills.append(skill)
        diagnostics.extend(skill_diags)

    return LoadSkillsResult(skills, diagnostics)


def load_skills(
    cwd: str,
    skill_paths: list[str] | None = None,
    agent_dir: str | None = None,
    include_defaults: bool = True,
) -> LoadSkillsResult:
    """
    Load skills from all configured locations.

    Args:
        cwd: Working directory for project-local skills
        skill_paths: Parent directories containing skill subdirectories.
                     Each skill subdirectory must contain a SKILL.md file.
                     Example structure:
                       path_a/
                       ├── skill_dir1/
                       │   └── SKILL.md
                       ├── skill_dir2/
                       │   └── SKILL.md
        agent_dir: Agent config directory for global skills
        include_defaults: Include default skills directories

    Returns:
        LoadSkillsResult with skills and diagnostics
    """
    all_skills = []
    all_diagnostics = []
    seen_names: dict[str, str] = {}
    seen_paths: set[str] = set()
    seen_skill_roots: set[str] = set()

    project_skills_dir = os.path.realpath(os.path.join(cwd, ".picho", "skills"))

    def add_result(result: LoadSkillsResult, location: str):
        nonlocal all_skills, all_diagnostics

        for diag in result.diagnostics:
            all_diagnostics.append(diag)

        for skill in result.skills:
            real_path = skill.file_path
            try:
                real_path = os.path.realpath(skill.file_path)
            except Exception:
                pass

            if real_path in seen_paths:
                continue
            seen_paths.add(real_path)

            if skill.name in seen_names:
                all_diagnostics.append(
                    Diagnostic(
                        type="warning",
                        message=f'duplicate skill name "{skill.name}" (first: {seen_names[skill.name]}, second: {skill.file_path})',
                        path=skill.file_path,
                    )
                )
                continue

            seen_names[skill.name] = skill.file_path
            all_skills.append(skill)

    explicit_paths = skill_paths or []

    for path in explicit_paths:
        expanded = os.path.expanduser(path)
        full_path = expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)
        real_full_path = os.path.realpath(full_path)
        is_default_project_path = real_full_path == project_skills_dir

        if real_full_path in seen_skill_roots:
            continue
        seen_skill_roots.add(real_full_path)

        if os.path.isfile(full_path):
            all_diagnostics.append(
                Diagnostic(
                    type="warning",
                    message=f"skill_path must be a parent directory, not a file: {full_path}",
                    path=full_path,
                )
            )
            continue

        if not os.path.isdir(full_path):
            if not is_default_project_path:
                all_diagnostics.append(
                    Diagnostic(
                        type="warning",
                        message=f"skill path does not exist: {full_path}",
                        path=full_path,
                    )
                )
            continue

        skill_md_path = os.path.join(full_path, "SKILL.md")
        if os.path.exists(skill_md_path):
            all_diagnostics.append(
                Diagnostic(
                    type="warning",
                    message=f"skill_path must be a parent directory containing skill subdirectories, not a skill directory itself: {full_path}",
                    path=full_path,
                )
            )
            continue

        result = load_skills_from_dir(full_path, "config")
        add_result(result, "config")

        if not result.skills and not is_default_project_path:
            all_diagnostics.append(
                Diagnostic(
                    type="warning",
                    message=f"no skills found in skill path: {full_path} (expected subdirectories with SKILL.md)",
                    path=full_path,
                )
            )

    if include_defaults:
        if (
            os.path.isdir(project_skills_dir)
            and project_skills_dir not in seen_skill_roots
        ):
            seen_skill_roots.add(project_skills_dir)
            result = load_skills_from_dir(project_skills_dir, "project")
            add_result(result, "project")

        if agent_dir:
            global_skills_dir = os.path.join(agent_dir, "skills")
            real_global_skills_dir = os.path.realpath(global_skills_dir)
            if (
                os.path.isdir(global_skills_dir)
                and real_global_skills_dir not in seen_skill_roots
            ):
                seen_skill_roots.add(real_global_skills_dir)
                result = load_skills_from_dir(global_skills_dir, "global")
                add_result(result, "global")

    return LoadSkillsResult(all_skills, all_diagnostics)


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """
    Format skills for inclusion in a system prompt.
    Uses XML format per Agent Skills standard.

    Skills with disable_model_invocation=True are excluded.
    """
    visible_skills = [s for s in skills if not s.disable_model_invocation]

    if not visible_skills:
        return ""

    lines = [
        "",
        "The following skills provide specialized instructions for specific tasks.",
        "Use the read tool to load a skill's file when the task matches its description.",
        "When a skill file references a relative path, resolve it against the skill directory.",
        "",
        "<available_skills>",
    ]

    for skill in visible_skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape_xml(skill.name)}</name>")
        lines.append(f"    <description>{_escape_xml(skill.description)}</description>")
        lines.append(f"    <location>{_escape_xml(skill.file_path)}</location>")
        lines.append("  </skill>")

    lines.append("</available_skills>")

    return "\n".join(lines)

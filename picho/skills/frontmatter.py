"""
Frontmatter parser for markdown files with YAML metadata.

Supports the standard YAML frontmatter format:
---
name: skill-name
description: A description
---
Body content here
"""

from __future__ import annotations

from typing import Any


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _extract_frontmatter(content: str) -> tuple[str | None, str]:
    """
    Extract YAML frontmatter from content.

    Returns:
        (yaml_string, body) - yaml_string is None if no valid frontmatter
    """
    normalized = _normalize_newlines(content)

    if not normalized.startswith("---"):
        return None, normalized

    end_index = normalized.find("\n---", 3)
    if end_index == -1:
        return None, normalized

    yaml_string = normalized[4:end_index]
    body = normalized[end_index + 4 :].strip()

    return yaml_string, body


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML frontmatter from markdown content.

    Args:
        content: Raw markdown content with optional frontmatter

    Returns:
        (frontmatter_dict, body_content)

    Example:
        >>> content = '''---
        ... name: my-skill
        ... description: A skill
        ... ---
        ...
        ... Body here'''
        >>> fm, body = parse_frontmatter(content)
        >>> fm['name']
        'my-skill'
        >>> body
        'Body here'
    """
    yaml_string, body = _extract_frontmatter(content)

    if yaml_string is None:
        return {}, body

    try:
        import yaml

        parsed = yaml.safe_load(yaml_string)
        if parsed is None:
            return {}, body
        if not isinstance(parsed, dict):
            return {}, body
        return parsed, body
    except Exception:
        return {}, body


def strip_frontmatter(content: str) -> str:
    """
    Remove frontmatter from content and return only the body.
    """
    _, body = _extract_frontmatter(content)
    return body

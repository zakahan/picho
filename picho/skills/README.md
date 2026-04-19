# Skills Module

Skill loading and management for picho.

## Overview

This module provides skill loading from markdown files with YAML frontmatter. Skills are specialized instructions for specific tasks.

## Architecture

```
skills/
├── __init__.py          # Module exports
├── types.py             # Type definitions
├── frontmatter.py       # YAML frontmatter parsing
└── loader.py            # Skill loading
```

## What are Skills?

Skills are markdown files with YAML frontmatter that provide specialized instructions:

```markdown
---
name: code-review
description: Review code for quality and best practices
version: 1.0.0
author: picho
tags:
  - code
  - review
---

# Code Review Skill

You are a code reviewer. Your task is to...

## Guidelines

1. Check for bugs
2. Review for performance
3. Suggest improvements
```

## Skill Types

```python
from picho.skills import Skill, SkillFrontmatter, LoadSkillsResult

# Skill frontmatter
frontmatter = SkillFrontmatter(
    name="code-review",
    description="Review code for quality",
    version="1.0.0",
    author="picho",
    tags=["code", "review"],
)

# Skill
skill = Skill(
    name="code-review",
    frontmatter=frontmatter,
    content="# Code Review Skill\n\n...",
    path="/path/to/skill.md",
)
```

## Loading Skills

### Load from Directory

```python
from picho.skills import load_skills_from_dir

result = load_skills_from_dir("/path/to/skills", "custom")

for skill in result.skills:
    print(f"Loaded: {skill.name}")

for diag in result.diagnostics:
    print(f"Warning: {diag.message}")
```

### Load Skills

```python
from picho.skills import load_skills

result = load_skills(
    cwd="/workspace",
    skill_paths=["/path/to/skills"],
    include_defaults=True,
)
```

### Format Skills for Prompt

```python
from picho.skills import format_skills_for_prompt

prompt = format_skills_for_prompt(result.skills)
# Returns formatted string for injection into instructions
```

## Frontmatter Parsing

```python
from picho.skills import parse_frontmatter, strip_frontmatter

# Parse frontmatter from content
frontmatter, remaining = parse_frontmatter(content)

# Or strip frontmatter
content_only = strip_frontmatter(content)
```

## Skill Directory Structure

```
skills/
├── code-review/
│   └── SKILL.md         # Skill definition
├── debug/
│   └── SKILL.md
└── skill-creator/
    ├── SKILL.md
    └── agents/          # Additional resources
        ├── analyzer.md
        └── comparator.md
```

## Configuration

Skills can be configured in `config.json`:

```json
{
    "agent": {
        "builtin": {
            "skill": ["code-review", "debug"]
        },
        "skill_paths": ["/path/to/custom/skills"]
    }
}
```

## Usage Examples

### Basic Usage

```python
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

for skill in result.skills:
    print(f"Skill: {skill.name}")
    print(f"Description: {skill.frontmatter.description}")
```

### With Agent

```python
from picho.agent import Agent
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

agent = Agent(
    model=model,
    instructions="You are a helpful assistant.",
    skills=result.skills,
)

# Skills are automatically injected into instructions
```

### Custom Skill Path

```python
result = load_skills(
    cwd="/workspace",
    skill_paths=["/custom/skills"],
    include_defaults=False,
)
```

## Diagnostics

The loader provides diagnostics for issues:

```python
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

for diag in result.diagnostics:
    if diag.type == "warning":
        print(f"Warning: {diag.message} ({diag.path})")
    elif diag.type == "error":
        print(f"Error: {diag.message} ({diag.path})")
```

## License

MIT

# Skills 模块

picho 的技能加载和管理。

## 概述

本模块提供从带有 YAML frontmatter 的 markdown 文件加载技能的功能。技能是针对特定任务的专业指令。

## 架构

```
skills/
├── __init__.py          # 模块导出
├── types.py             # 类型定义
├── frontmatter.py       # YAML frontmatter 解析
└── loader.py            # 技能加载
```

## 什么是技能？

技能是带有 YAML frontmatter 的 markdown 文件，提供专业指令：

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

## 技能类型

```python
from picho.skills import Skill, SkillFrontmatter, LoadSkillsResult

# 技能 frontmatter
frontmatter = SkillFrontmatter(
    name="code-review",
    description="Review code for quality",
    version="1.0.0",
    author="picho",
    tags=["code", "review"],
)

# 技能
skill = Skill(
    name="code-review",
    frontmatter=frontmatter,
    content="# Code Review Skill\n\n...",
    path="/path/to/skill.md",
)
```

## 加载技能

### 从目录加载

```python
from picho.skills import load_skills_from_dir

result = load_skills_from_dir("/path/to/skills", "custom")

for skill in result.skills:
    print(f"Loaded: {skill.name}")

for diag in result.diagnostics:
    print(f"Warning: {diag.message}")
```

### 加载技能

```python
from picho.skills import load_skills

result = load_skills(
    cwd="/workspace",
    skill_paths=["/path/to/skills"],
    include_defaults=True,
)
```

### 格式化技能为提示

```python
from picho.skills import format_skills_for_prompt

prompt = format_skills_for_prompt(result.skills)
# 返回格式化的字符串，用于注入到指令中
```

## Frontmatter 解析

```python
from picho.skills import parse_frontmatter, strip_frontmatter

# 从内容解析 frontmatter
frontmatter, remaining = parse_frontmatter(content)

# 或剥离 frontmatter
content_only = strip_frontmatter(content)
```

## 技能目录结构

```
skills/
├── code-review/
│   └── SKILL.md         # 技能定义
├── debug/
│   └── SKILL.md
└── skill-creator/
    ├── SKILL.md
    └── agents/          # 附加资源
        ├── analyzer.md
        └── comparator.md
```

## 配置

技能可以在 `config.json` 中配置：

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

## 使用示例

### 基本使用

```python
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

for skill in result.skills:
    print(f"Skill: {skill.name}")
    print(f"Description: {skill.frontmatter.description}")
```

### 与 Agent 一起使用

```python
from picho.agent import Agent
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

agent = Agent(
    model=model,
    instructions="You are a helpful assistant.",
    skills=result.skills,
)

# 技能会自动注入到指令中
```

### 自定义技能路径

```python
result = load_skills(
    cwd="/workspace",
    skill_paths=["/custom/skills"],
    include_defaults=False,
)
```

## 诊断

加载器提供问题诊断：

```python
from picho.skills import load_skills

result = load_skills(cwd="/workspace")

for diag in result.diagnostics:
    if diag.type == "warning":
        print(f"Warning: {diag.message} ({diag.path})")
    elif diag.type == "error":
        print(f"Error: {diag.message} ({diag.path})")
```

## 许可证

MIT

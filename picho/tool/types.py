"""
Tool Module

Unified Tool definition for both LLM interaction and tool execution.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class ToolParameter:
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    content: list = field(default_factory=list)
    details: Any = None
    is_error: bool = False


ToolUpdateCallback = Callable[[ToolResult], None]


@dataclass
class Tool:
    name: str = ""
    description: str = ""
    parameters: ToolParameter | None = None
    label: str = ""
    execute: (
        Callable[
            [str, dict[str, Any], asyncio.Event | None, ToolUpdateCallback | None],
            Awaitable[ToolResult],
        ]
        | None
    ) = None

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        parameters: ToolParameter | None = None,
        label: str = "",
        execute: Callable | None = None,
    ) -> "Tool":
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            label=label or name,
            execute=execute,
        )

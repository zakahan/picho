"""
pi_tool decorator for creating tools from functions
"""

import asyncio
import inspect
from typing import Any, Callable, get_type_hints

from picho.tool import Tool, ToolParameter, ToolResult


def pi_tool(
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, dict[str, Any]] | None = None,
):
    """
    Decorator to convert a Python function into a Tool.

    Usage:
        @pi_tool()
        def my_function(arg1: str, arg2: int) -> str:
            '''Function description here'''
            return "result"

        @pi_tool(
            name="custom_name",
            description="Custom description",
            parameters={
                "arg1": {"type": "string", "description": "First argument"},
                "arg2": {"type": "integer", "description": "Second argument"},
            }
        )
        def my_function(arg1: str, arg2: int) -> str:
            return "result"

    Args:
        name: Tool name (defaults to function name)
        description: Tool description (defaults to function docstring)
        parameters: Parameter descriptions (defaults to empty, types inferred from hints)
    """

    def decorator(func: Callable) -> Tool:
        tool_name = name or func.__name__

        tool_description = description
        if tool_description is None:
            doc = func.__doc__
            if doc:
                lines = doc.strip().split("\n")
                tool_description = lines[0].strip()
            else:
                tool_description = f"Tool: {tool_name}"

        sig = inspect.signature(func)
        hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_info: dict[str, Any] = {}

            if parameters and param_name in parameters:
                param_info = parameters[param_name].copy()
            else:
                param_type = hints.get(param_name, str)
                param_info["type"] = _python_type_to_json(param_type)
                param_info["description"] = ""

            properties[param_name] = param_info

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        tool_parameters = ToolParameter(
            type="object",
            properties=properties,
            required=required,
        )

        async def execute(
            tool_call_id: str,
            params: dict[str, Any],
            signal: Any = None,
            on_update: Any = None,
        ) -> ToolResult:
            kwargs = {k: v for k, v in params.items() if k in sig.parameters}

            if asyncio.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                result = func(**kwargs)

            if isinstance(result, ToolResult):
                return result

            from picho.provider.types import TextContent

            if result is None:
                return ToolResult(content=[TextContent(type="text", text="")])

            if isinstance(result, str):
                return ToolResult(content=[TextContent(type="text", text=result)])

            return ToolResult(content=[TextContent(type="text", text=str(result))])

        return Tool(
            name=tool_name,
            description=tool_description,
            parameters=tool_parameters,
            label=tool_name,
            execute=execute,
        )

    return decorator


def _python_type_to_json(python_type: Any) -> str:
    """Convert Python type hint to JSON schema type."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    origin = getattr(python_type, "__origin__", None)
    if origin is not None:
        if origin is list:
            return "array"
        if origin is dict:
            return "object"

    return type_map.get(python_type, "string")

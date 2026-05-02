from __future__ import annotations

import importlib
import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from picho.tool.executor import Executor
from picho.tool.types import Tool


@dataclass
class ToolFactoryContext:
    workspace: str
    cache_root: str
    config: Any
    executor: Executor


ToolFactory = Callable[[ToolFactoryContext], Tool | list[Tool]]


def load_custom_tools(
    tool_specs: list[str],
    context: ToolFactoryContext,
) -> list[Tool]:
    tools: list[Tool] = []
    for spec in tool_specs:
        factory = _load_tool_factory(spec, context.workspace)
        result = factory(context)
        if inspect.isawaitable(result):
            raise TypeError(
                f"Custom tool factory '{spec}' must be synchronous, got awaitable"
            )
        tools.extend(_normalize_factory_result(spec, result))
    return tools


def _load_tool_factory(spec: str, workspace: str) -> ToolFactory:
    module_spec, separator, attr_name = spec.partition(":")
    if not separator or not attr_name:
        raise ValueError(
            f"Custom tool spec must use 'module:function' or 'path.py:function': {spec}"
        )

    module = _load_module(module_spec, workspace)
    factory: Any = module
    for part in attr_name.split("."):
        factory = getattr(factory, part)

    if not callable(factory):
        raise TypeError(f"Custom tool factory is not callable: {spec}")
    return factory


def _load_module(module_spec: str, workspace: str) -> Any:
    module_path = Path(module_spec)
    if module_path.suffix == ".py":
        resolved_path = module_path
        if not resolved_path.is_absolute():
            resolved_path = Path(workspace) / resolved_path
        resolved_path = resolved_path.resolve()

        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Custom tool factory file not found: {resolved_path}"
            )

        module_name = f"picho_custom_tool_{_sanitize_module_name(resolved_path.stem)}"
        spec_obj = importlib.util.spec_from_file_location(module_name, resolved_path)
        if spec_obj is None or spec_obj.loader is None:
            raise ImportError(
                f"Cannot create module spec for custom tool: {resolved_path}"
            )

        module = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(module)
        return module

    return importlib.import_module(module_spec)


def _normalize_factory_result(spec: str, result: Tool | list[Tool]) -> list[Tool]:
    if isinstance(result, Tool):
        return [result]

    if not isinstance(result, list):
        raise TypeError(
            f"Custom tool factory '{spec}' must return Tool or list[Tool], got {type(result).__name__}"
        )

    for tool in result:
        if not isinstance(tool, Tool):
            raise TypeError(
                f"Custom tool factory '{spec}' returned non-Tool item: {type(tool).__name__}"
            )
    return result


def _sanitize_module_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)

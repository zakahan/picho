"""
Custom read extension loader.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from picho.logger import get_logger, log_exception
from picho.tool import ToolResult

_log = get_logger(__name__)


ReadExtensionExecutor = Callable[
    ["ReadExtensionContext"], ToolResult | Awaitable[ToolResult]
]


@dataclass
class ReadExtensionContext:
    tool_call_id: str
    params: dict[str, Any]
    requested_path: str
    resolved_path: str
    offset: int | None
    limit: int | None
    executor: Any
    cache_root: str
    signal: Any = None


@dataclass
class ReadExtension:
    name: str
    extensions: list[str]
    execute: ReadExtensionExecutor


def load_read_extensions(
    extension_specs: list[str], workspace: str
) -> list[ReadExtension]:
    loaded_extensions: list[ReadExtension] = []
    for spec in extension_specs:
        try:
            module = _load_extension_module(spec, workspace)
            module_extensions = getattr(module, "READ_EXTENSIONS", None)
            if module_extensions is None:
                _log.warning("Read extension module has no READ_EXTENSIONS: %s", spec)
                continue

            for extension in module_extensions:
                if _is_valid_extension(extension):
                    loaded_extensions.append(
                        ReadExtension(
                            name=extension.name,
                            extensions=[
                                suffix.lower() for suffix in extension.extensions
                            ],
                            execute=extension.execute,
                        )
                    )
                else:
                    _log.warning(
                        "Ignore invalid read extension from %s: %r", spec, extension
                    )
        except Exception as error:
            log_exception(
                _log,
                "Failed to load read extension",
                error,
                spec=spec,
                workspace=workspace,
            )
    return loaded_extensions


def find_read_extension(
    resolved_path: str,
    extensions: list[ReadExtension],
) -> ReadExtension | None:
    suffix = Path(resolved_path).suffix.lower()
    for extension in extensions:
        if suffix in extension.extensions:
            return extension
    return None


async def execute_read_extension(
    extension: ReadExtension,
    context: ReadExtensionContext,
) -> ToolResult:
    result = extension.execute(context)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, ToolResult):
        raise TypeError(
            f"Read extension '{extension.name}' must return ToolResult, got {type(result).__name__}"
        )
    return result


def _load_extension_module(spec: str, workspace: str) -> Any:
    module_path = Path(spec)
    if module_path.suffix == ".py":
        resolved_path = module_path
        if not resolved_path.is_absolute():
            resolved_path = Path(workspace) / resolved_path
        resolved_path = resolved_path.resolve()

        if not resolved_path.exists():
            raise FileNotFoundError(f"Read extension file not found: {resolved_path}")

        module_name = (
            f"picho_read_extension_{_sanitize_module_name(resolved_path.stem)}"
        )
        spec_obj = importlib.util.spec_from_file_location(module_name, resolved_path)
        if spec_obj is None or spec_obj.loader is None:
            raise ImportError(
                f"Cannot create module spec for read extension: {resolved_path}"
            )

        module = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(module)
        return module

    return importlib.import_module(spec)


def _is_valid_extension(extension: Any) -> bool:
    return (
        hasattr(extension, "name")
        and hasattr(extension, "extensions")
        and hasattr(extension, "execute")
        and callable(extension.execute)
    )


def _sanitize_module_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)

"""
Built-in tools for picho
"""

from picho.tool.executor import (
    Executor,
    HostExecutor,
    DockerExecutor,
    create_executor,
)

__all__ = [
    "Executor",
    "HostExecutor",
    "DockerExecutor",
    "create_executor",
    "create_read_tool",
    "create_write_tool",
    "create_bash_tool",
    "create_edit_tool",
    "create_builtin_tools",
]


def create_read_tool(
    executor: Executor, read_config=None, cache_root: str | None = None
):
    from .read import create_read_tool as _create_read_tool

    return _create_read_tool(executor, read_config=read_config, cache_root=cache_root)


def create_write_tool(executor: Executor):
    from .write import create_write_tool as _create_write_tool

    return _create_write_tool(executor)


def create_bash_tool(
    executor: Executor, env_path: str | None = None, init_command: str | None = None
):
    from .bash import create_bash_tool as _create_bash_tool

    return _create_bash_tool(executor, env_path=env_path, init_command=init_command)


def create_edit_tool(executor: Executor):
    from .edit import create_edit_tool as _create_edit_tool

    return _create_edit_tool(executor)


def create_builtin_tools(
    executor: Executor,
    env_path: str | None = None,
    init_command: str | None = None,
    read_config=None,
    cache_root: str | None = None,
) -> list:
    """
    Create all built-in tools.

    Args:
        executor: Executor instance for command execution
        env_path: Optional path to a .env file to load environment variables from
        init_command: Optional command to execute before each bash command (e.g., "export PATH=/my/python:$PATH")

    Returns a list of Tool instances for common operations:
    - read: Read file contents
    - write: Write content to files
    - bash: Execute bash commands
    - edit: Edit files by replacing text
    """
    return [
        create_read_tool(executor, read_config=read_config, cache_root=cache_root),
        create_bash_tool(executor, env_path=env_path, init_command=init_command),
        create_edit_tool(executor),
        create_write_tool(executor),
    ]

# Tool Module

Tool definition and executor abstraction for picho.

## Overview

This module provides:

- Unified `Tool` class for LLM interaction and execution
- Executor abstraction for different execution environments
- Output truncation utilities

## Architecture

```
tool/
├── __init__.py      # Module exports
├── types.py         # Tool type definitions
├── executor.py      # Executor abstraction
└── truncate.py      # Output truncation
```

## Tool Definition

### Tool

Unified tool definition for LLM interaction:

```python
from picho.tool import Tool, ToolParameter, ToolResult


async def my_execute(
        tool_call_id: str,
        params: dict,
        signal: asyncio.Event | None,
        on_update: Callable | None,
) -> ToolResult:
    # Execute tool logic
    return ToolResult(
        content=[{"type": "text", "text": "Result"}],
    )


tool = Tool.create(
    name="my_tool",
    description="My custom tool",
    parameters=ToolParameter(
        type="object",
        properties={"input": {"type": "string"}},
        required=["input"],
    ),
    execute=my_execute,
)
```

### ToolParameter

Define tool parameters:

```python
from picho.tool import ToolParameter

params = ToolParameter(
    type="object",
    properties={
        "path": {
            "type": "string",
            "description": "File path",
        },
        "limit": {
            "type": "integer",
            "description": "Max lines",
        },
    },
    required=["path"],
)
```

### ToolResult

Tool execution result:

```python
from picho.tool import ToolResult

result = ToolResult(
    content=[{"type": "text", "text": "Success"}],
    is_error=False,
)
```

## Executors

### HostExecutor

Execute commands on the local machine:

```python
from picho.tool import HostExecutor

executor = HostExecutor(cwd="/path/to/workspace")

result = await executor.exec("ls -la")
print(result.stdout)
print(result.code)
```

### DockerExecutor

Execute commands in a Docker container:

```python
from picho.tool import DockerExecutor

executor = DockerExecutor(
    container="my-container",
    cwd="/workspace",
)

result = await executor.exec("ls -la")
```

### create_executor

Factory function to create executors:

```python
from picho.tool import create_executor

executor = create_executor(
    executor_type="host",
    cwd="/workspace",
)
```

## Executor Interface

```python
from picho.tool import Executor


class MyExecutor(Executor):
    async def exec(
            self,
            command: str,
            timeout: int | None = None,
            signal: Any = None,
    ) -> ExecResult:
        # Implement execution logic
        pass

    def get_workspace_path(self, host_path: str) -> str:
        # Convert host path to executor path
        pass
```

## Progress Updates

For long-running operations:

```python
async def execute_with_progress(
    tool_call_id: str,
    params: dict,
    signal: asyncio.Event | None,
    on_update: Callable | None,
):
    for i in range(100):
        if signal and signal.is_set():
            return ToolResult(
                content=[{"type": "text", "text": "Aborted"}],
                is_error=True,
            )
        
        # Do work
        do_step(i)
        
        # Report progress
        if on_update:
            on_update(ToolResult(
                content=[{"type": "text", "text": f"Progress: {i+1}/100"}],
            ))
    
    return ToolResult(
        content=[{"type": "text", "text": "Done!"}],
    )
```

## Output Truncation

```python
from picho.tool.truncate import truncate_output

# Truncate to max lines
truncated = truncate_output(
    content=long_output,
    max_lines=2000,
    max_chars=50000,
)
```

## Usage Examples

### With Agent

```python
from picho.agent import Agent
from picho.tool import Tool, ToolParameter, HostExecutor

executor = HostExecutor(cwd="/workspace")


async def read_file(tool_call_id, params, signal, on_update):
    path = params.get("path")
    result = await executor.exec(f"cat {path}")
    return ToolResult(
        content=[{"type": "text", "text": result.stdout}],
    )


read_tool = Tool.create(
    name="read",
    description="Read file contents",
    parameters=ToolParameter(
        type="object",
        properties={"path": {"type": "string"}},
        required=["path"],
    ),
    execute=read_file,
)

agent = Agent(model=model, tools=[read_tool])
```

### Error Handling

```python
async def safe_execute(tool_call_id, params, signal, on_update):
    try:
        result = risky_operation(params)
        return ToolResult(
            content=[{"type": "text", "text": result}],
        )
    except Exception as e:
        return ToolResult(
            content=[{"type": "text", "text": f"Error: {e}"}],
            is_error=True,
        )
```

## License

MIT

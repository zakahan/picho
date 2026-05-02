# Tool 模块

picho 的工具定义和执行器抽象。

## 概述

本模块提供：

- 统一的 `Tool` 类用于 LLM 交互和执行
- 不同执行环境的执行器抽象
- 输出截断工具

## 架构

```
tool/
├── __init__.py      # 模块导出
├── types.py         # 工具类型定义
├── executor.py      # 执行器抽象
└── truncate.py      # 输出截断
```

## 工具定义

### Tool

用于 LLM 交互的统一工具定义：

```python
from picho.tool import Tool, ToolParameter, ToolResult


async def my_execute(
        tool_call_id: str,
        params: dict,
        signal: asyncio.Event | None,
        on_update: Callable | None,
) -> ToolResult:
    # 执行工具逻辑
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

定义工具参数：

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

工具执行结果：

```python
from picho.tool import ToolResult

result = ToolResult(
    content=[{"type": "text", "text": "Success"}],
    is_error=False,
)
```

`ToolResult.content` 支持 picho 内容对象，例如
`TextContent(type="text", text="Success")`，也支持公开文档中的 dict 内容块，
例如 `{"type": "text", "text": "Success"}`。dict 内容块会在返回给模型前被
归一化，因此自定义工具可以继续使用上面的写法。

## 执行器

### HostExecutor

在本地机器执行命令：

```python
from picho.tool import HostExecutor

executor = HostExecutor(cwd="/path/to/workspace")

result = await executor.exec("ls -la")
print(result.stdout)
print(result.code)
```

### DockerExecutor

在 Docker 容器中执行命令：

```python
from picho.tool import DockerExecutor

executor = DockerExecutor(
    container="my-container",
    cwd="/workspace",
)

result = await executor.exec("ls -la")
```

### create_executor

创建执行器的工厂函数：

```python
from picho.tool import create_executor

executor = create_executor(
    executor_type="host",
    cwd="/workspace",
)
```

## 执行器接口

```python
from picho.tool import Executor


class MyExecutor(Executor):
    async def exec(
            self,
            command: str,
            timeout: int | None = None,
            signal: Any = None,
    ) -> ExecResult:
        # 实现执行逻辑
        pass

    def get_workspace_path(self, host_path: str) -> str:
        # 将主机路径转换为执行器路径
        pass
```

## 进度更新

对于长时间运行的操作：

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
        
        # 执行工作
        do_step(i)
        
        # 报告进度
        if on_update:
            on_update(ToolResult(
                content=[{"type": "text", "text": f"Progress: {i+1}/100"}],
            ))
    
    return ToolResult(
        content=[{"type": "text", "text": "Done!"}],
    )
```

## 输出截断

```python
from picho.tool.truncate import truncate_output

# 截断到最大行数
truncated = truncate_output(
    content=long_output,
    max_lines=2000,
    max_chars=50000,
)
```

## 使用示例

### 与 Agent 一起使用

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

### 错误处理

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

## 许可证

MIT

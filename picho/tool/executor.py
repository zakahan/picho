"""
Executor abstraction for command execution

Provides different execution environments:
- HostExecutor: Execute commands on the local machine
- DockerExecutor: Execute commands in a Docker container
- SSHExecutor: Execute commands over SSH (future)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import asyncio
import os
import signal
from typing import Any

from ..logger import get_logger

_log = get_logger(__name__)


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """Best-effort process termination for abort/timeout paths."""
    if proc.returncode is not None:
        return

    pid = proc.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await proc.wait()
        except ProcessLookupError:
            pass


def _merge_process_env(env: dict[str, str] | None) -> dict[str, str] | None:
    """
    Merge custom environment variables with the current process environment.

    This preserves essential variables like PATH while still allowing callers
    to override individual keys.
    """
    if env is None:
        return None

    merged = os.environ.copy()
    merged.update(env)
    return merged


@dataclass
class ExecResult:
    """Result of command execution"""

    stdout: str
    stderr: str
    code: int


class Executor(ABC):
    """
    Abstract executor for running bash commands.

    Supports different execution environments:
    - Host: Run commands on the local machine
    - Docker: Run commands in a Docker container
    - SSH: Run commands over SSH connection
    """

    @property
    @abstractmethod
    def env(self) -> dict[str, str] | None:
        """Get environment variables for command execution"""
        pass

    @abstractmethod
    async def exec(
        self,
        command: str,
        timeout: int | None = None,
        signal: Any = None,
    ) -> ExecResult:
        """
        Execute a bash command.

        Args:
            command: Bash command to execute
            timeout: Timeout in seconds (optional)
            signal: Abort signal (asyncio.Event, optional)

        Returns:
            ExecResult with stdout, stderr, and exit code
        """
        pass

    @abstractmethod
    def get_workspace_path(self, host_path: str) -> str:
        """
        Get the workspace path for this executor.

        Args:
            host_path: Path on the host machine

        Returns:
            Path as seen by the executor
        """
        pass


class HostExecutor(Executor):
    """
    Execute commands on the local machine.
    """

    def __init__(self, cwd: str | None = None, env: dict[str, str] | None = None):
        """
        Initialize host executor.

        Args:
            cwd: Working directory for command execution (defaults to current directory)
            env: Environment variables to inject into command execution (optional)
        """
        self.cwd = cwd or os.getcwd()
        self._env = env
        self._process_env = _merge_process_env(env)

    @property
    def env(self) -> dict[str, str] | None:
        return self._env

    async def exec(
        self,
        command: str,
        timeout: int | None = None,
        signal: Any = None,
    ) -> ExecResult:
        """Execute command on the host machine"""
        _log.debug(f"Host executor executing command: cwd={self.cwd} timeout={timeout}")

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True,
            executable="/bin/bash",
            cwd=self.cwd,
            env=self._process_env,
            start_new_session=True,
        )

        try:
            if signal:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(proc.communicate()),
                        asyncio.create_task(signal.wait()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if signal.is_set():
                    await _terminate_process(proc)
                    raise asyncio.CancelledError("Operation aborted by user")

                comm_task = done.pop()
                stdout, stderr = comm_task.result()
            else:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
        except asyncio.TimeoutError:
            await _terminate_process(proc)
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        except asyncio.CancelledError:
            await _terminate_process(proc)
            raise

        result = ExecResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            code=proc.returncode or 0,
        )
        _log.debug(
            f"Executor command completed: code={result.code} stdout_len={len(result.stdout)} stderr_len={len(result.stderr)}"
        )
        return result

    def get_workspace_path(self, host_path: str) -> str:
        """Host executor sees the actual path"""
        return host_path


class DockerExecutor(Executor):
    """
    Execute commands in a Docker container.
    """

    def __init__(
        self, container: str, cwd: str = "/workspace", env: dict[str, str] | None = None
    ):
        """
        Initialize Docker executor.

        Args:
            container: Docker container name or ID
            cwd: Working directory inside container
            env: Environment variables to inject into command execution (optional)
        """
        self.container = container
        self.cwd = cwd
        self._env = env
        self._process_env = _merge_process_env(env)

    @property
    def env(self) -> dict[str, str] | None:
        return self._env

    async def exec(
        self,
        command: str,
        timeout: int | None = None,
        signal: Any = None,
    ) -> ExecResult:
        """Execute command in Docker container"""
        _log.debug(
            f"Docker executor executing command: container={self.container} cwd={self.cwd} timeout={timeout}"
        )

        env_args = ""
        if self._env:
            for key, value in self._env.items():
                env_args += f"-e {key}={value} "

        docker_cmd = f"docker exec {env_args}{self.container} sh -c '{command}'"

        proc = await asyncio.create_subprocess_shell(
            docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True,
            executable="/bin/bash",
            env=self._process_env,
        )

        try:
            if signal:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(proc.communicate()),
                        asyncio.create_task(signal.wait()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if signal.is_set():
                    await _terminate_process(proc)
                    raise asyncio.CancelledError("Operation aborted by user")

                stdout, stderr = done.pop().result()
            else:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
        except asyncio.TimeoutError:
            await _terminate_process(proc)
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        except asyncio.CancelledError:
            await _terminate_process(proc)
            raise

        result = ExecResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            code=proc.returncode or 0,
        )
        _log.debug(
            f"Executor command completed: code={result.code} stdout_len={len(result.stdout)} stderr_len={len(result.stderr)}"
        )
        return result

    def get_workspace_path(self, host_path: str) -> str:
        """Docker container sees /workspace"""
        return self.cwd


def create_executor(
    cwd: str | None = None,
    executor_type: str = "host",
    env: dict[str, str] | None = None,
    **kwargs,
) -> Executor:
    """
    Create an executor instance.

    Args:
        cwd: Working directory
        executor_type: Type of executor ("host", "docker")
        env: Environment variables to inject into command execution (optional)
        **kwargs: Additional arguments for specific executor types
            - docker: container (required)

    Returns:
        Executor instance
    """
    if executor_type == "host":
        return HostExecutor(cwd=cwd, env=env)
    elif executor_type == "docker":
        container = kwargs.get("container")
        if not container:
            raise ValueError("Docker executor requires 'container' parameter")
        return DockerExecutor(container=container, cwd=cwd or "/workspace", env=env)
    else:
        raise ValueError(f"Unknown executor type: {executor_type}")

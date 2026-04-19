"""
Security policy for builtin tools
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Awaitable

from ..logger import get_logger

_log = get_logger(__name__)


@dataclass
class SecurityCheckResult:
    allowed: bool
    reason: str = ""
    requires_confirmation: bool = False
    confirmation_message: str = ""


DANGEROUS_PATTERNS = [
    (r"\brm\s+", "rm command - deletes files"),
    (r"\brm\s+-rf\b", "rm -rf - force delete recursively"),
    (r"\brm\s+-fr\b", "rm -fr - force delete recursively"),
    (r"\bchmod\s+", "chmod - changes file permissions"),
    (r"\bchown\s+", "chown - changes file ownership"),
    (r"\bmv\s+.*\s+/dev/null", "moving to /dev/null - destroys data"),
    (r"\b>\s*/dev/sd[a-z]", "writing directly to disk device"),
    (r"\bdd\s+.*of=/dev/", "dd to device - can destroy data"),
    (r"\bmkfs\b", "mkfs - formats filesystem"),
    (r"\bfdisk\b", "fdisk - partition editor"),
    (r"\bshutdown\b", "shutdown command"),
    (r"\breboot\b", "reboot command"),
    (r"\binit\s+[06]", "init 0/6 - shutdown/reboot"),
    (r"\biptables\b", "iptables - firewall rules"),
    (r"\bip6tables\b", "ip6tables - firewall rules"),
    (r"\bkill\s+-9\s+1\b", "kill -9 1 - kill init"),
    (r"\b:\(\)\{\s*:\|:\s*&\s*\};\s*:", "fork bomb"),
]

PROTECTED_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/root",
    "/boot",
    "/proc",
    "/sys",
]


def is_path_in_workspace(path: str, workspace: str) -> bool:
    """Check if path is within workspace"""
    try:
        abs_path = Path(path).resolve()
        abs_workspace = Path(workspace).resolve()

        try:
            abs_path.relative_to(abs_workspace)
            return True
        except ValueError:
            return False
    except Exception:
        return False


def check_path_security(path: str, workspace: str) -> SecurityCheckResult:
    """Check if path operation is allowed"""
    _log.debug(f"Checking path security: path={path} workspace={workspace}")
    if not path:
        _log.warning("Path security check failed: path is empty")
        return SecurityCheckResult(allowed=False, reason="Path is empty")

    abs_path = (
        Path(path).resolve() if Path(path).is_absolute() else Path(workspace) / path
    )
    abs_path = abs_path.resolve()
    abs_workspace = Path(workspace).resolve()

    for protected in PROTECTED_PATHS:
        try:
            if str(abs_path).startswith(protected) or abs_path == Path(protected):
                _log.warning(f"Path security check failed: protected path {protected}")
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"Access to protected system path: {protected}",
                )
        except Exception:
            pass

    try:
        abs_path.relative_to(abs_workspace)
    except ValueError:
        _log.warning("Path security check failed: outside workspace")
        return SecurityCheckResult(
            allowed=False, reason=f"Path '{path}' is outside workspace '{workspace}'"
        )

    _log.debug("Path security check passed")
    return SecurityCheckResult(allowed=True)


def check_command_security(command: str) -> SecurityCheckResult:
    """Check if command is safe to execute"""
    _log.debug(f"Checking command security: {command[:50]}...")
    command_lower = command.lower()

    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower):
            _log.warning(f"Dangerous command detected: {description}")
            return SecurityCheckResult(
                allowed=True,
                requires_confirmation=True,
                confirmation_message=f"Dangerous command detected: {description}. Proceed?",
                reason=description,
            )

    for protected in PROTECTED_PATHS:
        if protected in command:
            _log.warning(f"Command contains protected path: {protected}")
            return SecurityCheckResult(
                allowed=False, reason=f"Access to protected system path: {protected}"
            )

    _log.debug("Command security check passed")
    return SecurityCheckResult(allowed=True)


def validate_path(path: str, workspace: str) -> SecurityCheckResult:
    """Alias for check_path_security"""
    return check_path_security(path, workspace)


def validate_command(command: str) -> SecurityCheckResult:
    """Alias for check_command_security"""
    return check_command_security(command)


class SecurityPolicy:
    def __init__(
        self,
        workspace: str,
        confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.workspace = str(Path(workspace).resolve())
        self.confirm_callback = confirm_callback

    def check_path(self, path: str) -> SecurityCheckResult:
        return check_path_security(path, self.workspace)

    def check_command(self, command: str) -> SecurityCheckResult:
        result = check_command_security(command)

        if result.requires_confirmation and self.confirm_callback:
            return result

        return result

    async def validate_path(self, path: str) -> str:
        """Validate path and return absolute path, or raise error"""
        result = self.check_path(path)
        if not result.allowed:
            raise PermissionError(result.reason)

        if Path(path).is_absolute():
            return path
        return str(Path(self.workspace) / path)

    async def validate_command(self, command: str) -> str:
        """Validate command, ask for confirmation if needed"""
        result = self.check_command(command)

        if not result.allowed:
            raise PermissionError(result.reason)

        if result.requires_confirmation:
            if self.confirm_callback:
                confirmed = await self.confirm_callback(result.confirmation_message)
                if not confirmed:
                    raise PermissionError(f"User denied: {result.reason}")
            else:
                raise PermissionError(
                    f"Dangerous command requires confirmation: {result.reason}"
                )

        return command

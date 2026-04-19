"""
Dangerous command detection callback

Provides a before_tool_callback that detects dangerous bash commands
and requests user confirmation before execution.
"""

import re
from typing import Any

from ..agent.types import CallbackContext
from ..tool import ToolResult
from ..provider.types import TextContent
from .confirmation import get_confirmation_manager


DANGEROUS_PATTERNS = [
    (r"\brm\b", "rm (delete files/directories)"),
    (r"\brm\s+-[rf]+\s+", "rm -rf (force delete recursively)"),
    (r"\bmv\s+.*\s+/dev/null", "mv to /dev/null (destroy data)"),
    (r"\bchmod\s+[0-7]{3,4}\s+", "chmod (change permissions)"),
    (r"\bchown\b", "chown (change ownership)"),
    (r"\bdd\s+.*of=", "dd (disk operations)"),
    (r"\bmkfs\b", "mkfs (format filesystem)"),
    (r"\bfdisk\b", "fdisk (partition editor)"),
    (r"\bshutdown\b", "shutdown system"),
    (r"\breboot\b", "reboot system"),
    (r"\binit\s+[06]", "init 0/6 (shutdown/reboot)"),
    (r">\s*/dev/sd[a-z]", "write directly to disk"),
    (r"\biptables\b", "iptables (firewall rules)"),
    (r"\bkill\s+-9\s+1\b", "kill init process"),
    (r"\buserdel\b", "userdel (delete user)"),
    (r"\bpasswd\s+", "passwd (change password)"),
    (r"\bsudo\s+rm\b", "sudo rm (delete as root)"),
    (r"\bsudo\s+chmod\b", "sudo chmod (change permissions as root)"),
    (r"curl.*\|\s*bash", "curl | bash (execute remote script)"),
    (r"wget.*\|\s*bash", "wget | bash (execute remote script)"),
]


def detect_dangerous_command(command: str) -> list[tuple[str, str]]:
    results = []
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            results.append((pattern, description))
    return results


async def bash_security_callback(
    ctx: CallbackContext,
    tool_name: str,
    args: dict[str, Any],
) -> ToolResult | None:
    if tool_name != "bash":
        return None

    command = args.get("command", "")
    if not command:
        return None

    dangers = detect_dangerous_command(command)
    if not dangers:
        return None

    descriptions = [d[1] for d in dangers]
    danger_list = "\n".join(f"  - {d}" for d in descriptions)

    manager = get_confirmation_manager()

    approved = await manager.request_confirmation(
        title="Dangerous Command Detected",
        message=f"Dangerous command detected:\n```\n{command}\n```\n\nDetected risks:\n{danger_list}\n\nDo you want to execute this command?",
        details={
            "command": command,
            "dangers": descriptions,
        },
    )

    if not approved:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"""[TOOL CALL BLOCKED]

Command: {command}
Status: REJECTED by user
Reason: {danger_list}

This command was identified as potentially dangerous and has been blocked.
Please do NOT retry this command. Ask the user for alternative approaches.""",
                )
            ],
            is_error=True,
        )

    return None


def create_bash_security_callback():
    return bash_security_callback

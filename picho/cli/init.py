"""
picho init command - Initialize .picho directory with config files
"""

import json
import os
from pathlib import Path

import click

from ..provider.model.base import ProviderType


PROVIDER_PRESETS = {
    ProviderType.OPENAI_COMPLETION.value: {
        "model_name": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "description": "OpenAI Chat Completions API (gpt-4o, gpt-4o-mini, etc.)",
    },
    ProviderType.OPENAI_RESPONSES.value: {
        "model_name": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "description": "OpenAI Responses API (with reasoning support)",
    },
    ProviderType.ARK_RESPONSES.value: {
        "model_name": "doubao-seed-2-0-lite-260215",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "env_key": "ARK_API_KEY",
        "description": "Volcengine Ark API (Doubao models with reasoning)",
    },
    ProviderType.ANTHROPIC.value: {
        "model_name": "claude-sonnet-4-5",
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "description": "Anthropic Claude Messages API (tool use and thinking)",
    },
    ProviderType.GOOGLE.value: {
        "model_name": "gemini-3-flash-preview",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env_key": "GEMINI_API_KEY",
        "description": "Google Gemini API (multimodal and function calling)",
    },
    ProviderType.MOCK.value: {
        "model_name": "mock-model",
        "base_url": "mock://local",
        "env_key": "",
        "description": "Mock provider for local testing without API keys",
    },
}

DEFAULT_CONFIG = {
    "path": {
        "base": "",
        "cache": ".",
        "skills": [".picho/skills"],
    },
    "agent": {
        "instructions": "You are a helpful AI assistant named picho.",
        "thinking_level": "auto",
        "builtin": {
            "tool": ["read", "write", "bash", "edit"],
            "skill": ["code-review", "debug", "skill-creator"],
            "tool_config": {
                "read": {
                    "extensions": [],
                    "video_compression": {
                        "enabled": True,
                        "trigger_size_mb": 512,
                    },
                }
            },
        },
        "steering_mode": "one-at-a-time",
        "follow_up_mode": "one-at-a-time",
    },
    "session_manager": {
        "persist": True,
    },
}

DEFAULT_TUI_CONFIG = {
    "chat": {
        "show_thinking": False,
        "show_tool_execution": True,
        "show_tool_args": "low",
        "show_tool_result": "all",
        "stream_output": True,
        "prompt_prefix": "You",
    },
    "display": {
        "theme": "dark",
        "color_enabled": True,
    },
    "log": {
        "console_output": False,
    },
}


def get_default_cwd() -> str:
    return os.getcwd()


GLOBAL_CONFIG_DIR = Path.home() / ".picho"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"
GLOBAL_TUI_FILE = GLOBAL_CONFIG_DIR / "tui.json"


@click.command()
@click.option(
    "-p",
    "--provider",
    type=click.Choice(list(PROVIDER_PRESETS.keys())),
    help="LLM provider to use",
)
@click.option(
    "-m",
    "--model",
    "model_name",
    help="Model name (uses provider default if not specified)",
)
@click.option(
    "--base-url",
    "base_url",
    help="API base URL (uses provider default if not specified)",
)
@click.option(
    "-y",
    "--yes",
    "use_defaults",
    is_flag=True,
    help="Use default values without prompting",
)
@click.option(
    "--path",
    "target_path",
    type=click.Path(),
    default=".",
    help="Target directory to initialize (default: current directory)",
)
@click.option(
    "--auto",
    "use_global",
    is_flag=True,
    help="Use global config from ~/.picho as template (error if not found)",
)
def init(
    provider: str | None,
    model_name: str | None,
    base_url: str | None,
    use_defaults: bool,
    target_path: str,
    use_global: bool,
):
    """
    Initialize .picho directory with configuration files.

    Examples:

        \b
        # Interactive mode
        picho init

        \b
        # Quick init with OpenAI
        picho init -p openai-completion -y

        \b
        # Specify provider and model
        picho init -p ark-responses -m doubao-pro-32k

        \b
        # Initialize in specific directory
        picho init --path /path/to/project

        \b
        # Use global config as template
        picho init --auto
    """
    target_dir = Path(target_path).resolve()
    picho_dir = target_dir / ".picho"

    if picho_dir.exists():
        config_file = picho_dir / "config.json"
        tui_file = picho_dir / "tui.json"
        if config_file.exists() or tui_file.exists():
            if not click.confirm(
                f".picho directory already exists at {picho_dir}. Overwrite?",
                default=False,
            ):
                click.echo("Aborted.")
                return

    if use_global:
        _init_from_global_config(picho_dir, target_dir)
        return

    if provider is None:
        provider = _select_provider(use_defaults)

    preset = PROVIDER_PRESETS[provider]

    if model_name is None and not use_defaults:
        model_name = click.prompt(
            "Model name",
            default=preset["model_name"],
            type=str,
        )
    else:
        model_name = model_name or preset["model_name"]

    if base_url is None and not use_defaults:
        base_url = click.prompt(
            "Base URL",
            default=preset["base_url"],
            type=str,
        )
    else:
        base_url = base_url or preset["base_url"]

    _create_config_files(
        picho_dir=picho_dir,
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        cwd=str(target_dir),
    )

    click.echo(f"\n✓ Created .picho directory at {picho_dir}")
    click.echo("  - config.json")
    click.echo("  - tui.json")
    click.echo(f"\n  Provider: {provider}")
    click.echo(f"  Model: {model_name}")
    click.echo(f"  Base URL: {base_url}")
    click.echo(f"\n  Set your API key: export {preset['env_key']}=your-api-key")
    click.echo("  Then run: picho chat\n")


def _select_provider(use_defaults: bool) -> str:
    if use_defaults:
        return ProviderType.OPENAI_COMPLETION.value

    click.echo("\nSelect a provider:\n")
    providers = list(PROVIDER_PRESETS.keys())
    for i, (key, preset) in enumerate(PROVIDER_PRESETS.items(), 1):
        click.echo(f"  {i}. {key}")
        click.echo(f"     {preset['description']}")
        click.echo(f"     Default model: {preset['model_name']}")
        click.echo(f"     Env key: {preset['env_key']}")
        click.echo()

    choice = click.prompt(
        "Enter choice",
        type=click.IntRange(1, len(providers)),
        default=1,
    )
    return providers[choice - 1]


def _create_config_files(
    picho_dir: Path,
    provider: str,
    model_name: str,
    base_url: str,
    cwd: str,
):
    picho_dir.mkdir(parents=True, exist_ok=True)

    config = DEFAULT_CONFIG.copy()
    config["path"]["base"] = cwd
    config["agent"]["model"] = {
        "model_provider": provider,
        "model_name": model_name,
        "base_url": base_url,
    }

    config_file = picho_dir / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    tui_file = picho_dir / "tui.json"
    with open(tui_file, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_TUI_CONFIG, f, indent=2, ensure_ascii=False)


def _init_from_global_config(picho_dir: Path, target_dir: Path):
    if not GLOBAL_CONFIG_FILE.exists():
        click.echo(f"Error: Global config not found at {GLOBAL_CONFIG_FILE}", err=True)
        click.echo(
            "Please create it first with: picho init -p <provider> -y --path ~",
            err=True,
        )
        raise SystemExit(1)

    picho_dir.mkdir(parents=True, exist_ok=True)

    with open(GLOBAL_CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "path" not in config:
        config["path"] = {}
    config["path"]["base"] = str(target_dir)

    config_file = picho_dir / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    if GLOBAL_TUI_FILE.exists():
        with open(GLOBAL_TUI_FILE, "r", encoding="utf-8") as f:
            tui_config = json.load(f)
    else:
        tui_config = DEFAULT_TUI_CONFIG

    tui_file = picho_dir / "tui.json"
    with open(tui_file, "w", encoding="utf-8") as f:
        json.dump(tui_config, f, indent=2, ensure_ascii=False)

    model_info = config.get("agent", {}).get("model", {})
    provider = model_info.get("model_provider", "unknown")
    model_name = model_info.get("model_name", "unknown")

    click.echo(f"\n✓ Created .picho directory at {picho_dir}")
    click.echo("  - config.json (from global template)")
    click.echo("  - tui.json")
    click.echo(f"\n  Provider: {provider}")
    click.echo(f"  Model: {model_name}")
    click.echo("  Ready to use: picho chat\n")

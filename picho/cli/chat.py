import asyncio
import importlib.util
import sys
import logging
import traceback
from pathlib import Path

import click

from ..runner import Runner
from ..logger import format_exception, init_logging, get_logger, log_exception
from .config import load_cli_config
from .tui import ChatTUI
from .confirmation import create_confirmation_manager
from .security_callback import create_bash_security_callback

_log = get_logger(__name__)


def find_config() -> str | None:
    candidates = [
        Path.cwd() / ".picho" / "config.json",
        Path.cwd() / "config.json",
        Path.home() / ".picho" / "config.json",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def load_runner_from_module(module_path: str) -> Runner:
    path = Path(module_path)
    if not path.exists():
        raise ValueError(f"Runner module not found: {module_path}")

    spec = importlib.util.spec_from_file_location("runner_module", path)
    if not spec or not spec.loader:
        raise ValueError(f"Failed to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["runner_module"] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "runner"):
        raise ValueError(f"Module {module_path} must export a 'runner' variable")

    runner = module.runner
    if not isinstance(runner, Runner):
        raise ValueError(f"'runner' in {module_path} must be a Runner instance")

    return runner


@click.command(name="chat")
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True),
    help="Path to config JSON file",
)
@click.option(
    "-r",
    "--runner",
    "runner_path",
    type=click.Path(exists=True),
    help="Path to Python module that exports a 'runner' variable",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
def chat(config_path: str | None, runner_path: str | None, verbose: bool):
    """Start an interactive coding session with picho."""
    cli_config = load_cli_config()

    log_level = logging.DEBUG if verbose else logging.INFO
    init_logging(
        level=log_level,
        log_to_file=True,
        stream=sys.stderr if cli_config.log.console_output else None,
    )

    _log.info("Starting picho coding session")
    runner: Runner | None = None

    try:
        if runner_path:
            _log.info(f"Loading runner from module: {runner_path}")
            runner = load_runner_from_module(runner_path)
        else:
            if not config_path:
                config_path = find_config()

            if not config_path:
                click.echo("Error: No config file found.", err=True)
                click.echo(
                    "Please create .picho/config.json or use --runner option", err=True
                )
                sys.exit(1)

            _log.info(f"Using config: {config_path}")
            runner = Runner(config_type="json", config=config_path)

        init_logging(
            level=log_level,
            log_to_file=True,
            stream=sys.stderr if cli_config.log.console_output else None,
        )
        session_id = runner.create_session()

        confirmation_manager = create_confirmation_manager()
        security_callback = create_bash_security_callback()

        state = runner.get_session(session_id)
        if state:
            state.agent.register_callback("before_tool_callback", security_callback)

        cli_config = load_cli_config()
        chat_tui = ChatTUI(runner, session_id, cli_config, confirmation_manager)
        asyncio.run(chat_tui.run())
    except SystemExit:
        raise
    except Exception as err:
        log_exception(_log, "picho startup failed", err)
        click.echo("Error: picho failed to start.", err=True)
        click.echo(format_exception(err), err=True)
        if verbose:
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)
    finally:
        if runner is not None:
            runner.close_all()

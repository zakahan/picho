import click
from picho import __version__

from .chat import chat
from .init import init
from .telemetry import telemetry


@click.group()
@click.version_option(__version__, "-v", "--version", prog_name="picho")
def cli():
    """picho command line interface."""
    pass


@click.command()
def version():
    """Show picho version."""
    click.echo(f"picho version {__version__}")


cli.add_command(chat)
cli.add_command(init)
cli.add_command(telemetry)
cli.add_command(version)


if __name__ == "__main__":
    cli()

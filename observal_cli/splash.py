"""Splash art display for the Observal CLI."""

from __future__ import annotations

import logging
from importlib.resources import files

from rich.console import Console

logger = logging.getLogger(__name__)

ART_WIDTH = 80
COMPACT_BANNER = """\
[bold blue]█▀█[/bold blue] [bold cyan]█▄▄[/bold cyan] [bold blue]█▀[/bold blue] [bold cyan]█▀▀[/bold cyan] [bold blue]█▀█[/bold blue] [bold cyan]█ █[/bold cyan] [bold blue]▄▀█[/bold blue] [bold cyan]█[/bold cyan]
[bold blue]█▄█[/bold blue] [bold cyan]█▄█[/bold cyan] [bold blue]▄█[/bold blue] [bold cyan]██▄[/bold cyan] [bold blue]█▀▄[/bold blue] [bold cyan]▀▄▀[/bold cyan] [bold blue]█▀█[/bold blue] [bold cyan]█▄[/bold cyan]
"""


def print_splash(console: Console) -> None:
    """Display splash art on --version if terminal is wide enough."""
    try:
        asset_text = (
            files("observal_cli.assets").joinpath("splash.txt").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, TypeError) as exc:
        logger.debug("Could not load splash art: %s", exc)
        return

    width = console.size.width
    if width >= ART_WIDTH:
        console.out(asset_text, highlight=False)
    else:
        console.print(COMPACT_BANNER)

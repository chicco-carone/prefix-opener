from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from .cache import clear_cache, load_cache, load_theme, save_cache, save_theme
from .steam import discover_prefixes, steam_cache_fingerprint
from .ui import run_ui

app = typer.Typer(
    add_completion=False,
    help="Search installed Steam Proton prefixes and open one in your file browser.",
)


@app.command()
def open_prefix(
    refresh: Annotated[
        bool,
        typer.Option("--refresh", "-r", help="Ignore the cache and rescan Steam."),
    ] = False,
    steam_root: Annotated[
        list[Path] | None,
        typer.Option(
            "--steam-root",
            help="Steam root to scan. Repeat for multiple installations.",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear-cache", help="Delete cached scan results and exit."),
    ] = False,
) -> None:
    if clear:
        removed = clear_cache()
        typer.echo("Cache cleared." if removed else "No cache file found.")
        return

    if shutil.which("xdg-open") is None:
        raise typer.BadParameter("xdg-open was not found on PATH")

    roots = [root.expanduser().resolve() for root in steam_root] if steam_root else None
    scope = [str(root) for root in roots] if roots else None
    source_fingerprint = steam_cache_fingerprint(roots)
    games = (
        None
        if refresh
        else load_cache(scope=scope, source_fingerprint=source_fingerprint)
    )
    if games is None:
        typer.echo("Scanning Steam libraries...", err=True)
        games = discover_prefixes(roots)
        save_cache(
            games,
            scope=scope,
            source_fingerprint=steam_cache_fingerprint(roots),
        )

    if not games:
        typer.echo("No Proton prefixes found. Try --steam-root or --refresh.", err=True)
        raise typer.Exit(1)

    run_ui(games, load_theme(), save_theme)


def main() -> None:
    app()

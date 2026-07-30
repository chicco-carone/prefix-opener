from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Input, Label, OptionList
from textual.widgets.option_list import Option

from .pcgamingwiki import PCGamingWikiError, find_save_folder
from .steam import GamePrefix


class PrefixOpenerApp(App[None]):
    TITLE = "Steam Prefix Opener"
    SUB_TITLE = "Search Proton prefixes"
    CSS = """
    Screen {
        background: $surface;
    }

    #content {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    #search {
        margin-bottom: 1;
        border: tall $accent;
    }

    #count {
        color: $text-muted;
        margin-bottom: 1;
    }

    #games {
        height: 1fr;
        border: round $primary-darken-1;
    }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding(
            "shift+enter",
            "open_save_folder",
            "Saves",
            priority=True,
        ),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("left", "cursor_left", show=False, priority=True),
        Binding("right", "cursor_right", show=False, priority=True),
        Binding("/", "focus_search", "Search"),
        Binding("t", "change_theme", "Theme"),
    ]

    def __init__(
        self,
        games: list[GamePrefix],
        theme: str | None = None,
        on_theme_change: Callable[[str], None] | None = None,
    ) -> None:
        self.on_theme_change = on_theme_change
        super().__init__()
        if theme in self.available_themes:
            self.theme = theme
        self.games = games
        self.filtered_games = games
        self.game_indices = {
            game.prefix_path: index for index, game in enumerate(self.games)
        }

    def compose(self) -> ComposeResult:
        with Vertical(id="content"):
            yield Input(
                placeholder="Type a game name, AppID, or path",
                select_on_focus=False,
                id="search",
            )
            yield Label(id="count")
            yield OptionList(id="games")
        yield Footer()

    def on_mount(self) -> None:
        self._render_games(self.games)
        self.query_one(Input).focus()

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_left(self) -> None:
        search = self.query_one(Input)
        if not search.has_focus:
            selection = search.selection
            search.focus()
            search.selection = selection
        search.action_cursor_left()

    def action_cursor_right(self) -> None:
        search = self.query_one(Input)
        if not search.has_focus:
            selection = search.selection
            search.focus()
            search.selection = selection
        search.action_cursor_right()

    async def action_open_save_folder(self) -> None:
        game = self._highlighted_game()
        if game is None:
            return
        self.notify("Looking up the save folder on PCGamingWiki...", timeout=10)
        try:
            folder = await asyncio.to_thread(
                find_save_folder,
                game.app_id,
                game.compatdata_path,
                game.library_path,
                game.name,
            )
        except PCGamingWikiError as error:
            self.notify(str(error), title="Could not find save folder", severity="error")
            return
        self._open_path(folder, "Could not open save folder")

    def _watch_theme(self, theme_name: str) -> None:
        super()._watch_theme(theme_name)
        if self.on_theme_change is not None:
            self.on_theme_change(theme_name)

    @on(Input.Changed)
    def filter_games(self, event: Input.Changed) -> None:
        terms = event.value.casefold().split()
        filtered = [
            game
            for game in self.games
            if all(
                term in f"{game.name} {game.app_id} {game.prefix_path}".casefold()
                for term in terms
            )
        ]
        self._render_games(filtered)

    @on(Input.Submitted)
    def open_from_search(self) -> None:
        option_list = self.query_one(OptionList)
        index = option_list.highlighted
        if index is None and self.filtered_games:
            index = 0
        if index is not None:
            self._open_game(self.filtered_games[index])

    @on(OptionList.OptionSelected)
    def open_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self._open_game(self.games[int(event.option.id)])

    def _highlighted_game(self) -> GamePrefix | None:
        index = self.query_one(OptionList).highlighted
        if index is None and self.filtered_games:
            index = 0
        if index is None:
            return None
        return self.filtered_games[index]

    def _render_games(self, games: list[GamePrefix]) -> None:
        self.filtered_games = games
        options = []
        for game in games:
            original_index = self.game_indices[game.prefix_path]
            label = Text.assemble(
                (game.name, "bold"),
                (f"  AppID {game.app_id}\n", "dim"),
                (game.prefix_path, "cyan"),
            )
            options.append(Option(label, id=str(original_index)))
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        if games:
            option_list.highlighted = 0
        self.query_one("#count", Label).update(
            f"{len(games)} of {len(self.games)} prefixes"
        )

    def _open_game(self, game: GamePrefix) -> None:
        self._open_path(Path(game.prefix_path), "Could not open prefix")

    def _open_path(self, path: Path, error_title: str) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            self.notify(str(error), title=error_title, severity="error")
            return
        self.exit()


def run_ui(
    games: list[GamePrefix],
    theme: str | None = None,
    on_theme_change: Callable[[str], None] | None = None,
) -> None:
    PrefixOpenerApp(games, theme, on_theme_change).run()

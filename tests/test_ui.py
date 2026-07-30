from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, OptionList

from prefix_opener.steam import GamePrefix
from prefix_opener.ui import PrefixOpenerApp


def game(app_id: str, name: str) -> GamePrefix:
    path = f"/tmp/{app_id}/pfx"
    return GamePrefix(app_id, name, path, f"/tmp/{app_id}", "/tmp")


class PrefixOpenerAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_filters_by_name(self) -> None:
        app = PrefixOpenerApp([game("1", "Alpha"), game("2", "Beta")])

        async with app.run_test() as pilot:
            app.query_one(Input).value = "beta"
            await pilot.pause()

            self.assertEqual([item.name for item in app.filtered_games], ["Beta"])
            self.assertEqual(app.query_one(OptionList).option_count, 1)

    async def test_enter_opens_highlighted_prefix_and_exits(self) -> None:
        selected = game("1", "Alpha")
        app = PrefixOpenerApp([selected])

        with patch("prefix_opener.ui.subprocess.Popen") as popen:
            async with app.run_test() as pilot:
                await pilot.press("enter")

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["xdg-open", selected.prefix_path])

    async def test_up_and_down_navigate_the_game_list_from_search(self) -> None:
        app = PrefixOpenerApp([game("1", "Alpha"), game("2", "Beta")])

        async with app.run_test() as pilot:
            await pilot.press("down")
            self.assertEqual(app.query_one(OptionList).highlighted, 1)
            self.assertIs(app.focused, app.query_one(Input))

            await pilot.press("up")
            self.assertEqual(app.query_one(OptionList).highlighted, 0)

    async def test_left_and_right_move_the_search_cursor_from_game_list(self) -> None:
        app = PrefixOpenerApp([game("1", "Alpha")])

        async with app.run_test() as pilot:
            search = app.query_one(Input)
            search.value = "Alpha"
            await pilot.pause()
            search.cursor_position = 1
            app.query_one(OptionList).focus()

            await pilot.press("right")
            self.assertIs(app.focused, search)
            self.assertEqual(search.cursor_position, 2)

            app.query_one(OptionList).focus()
            await pilot.press("left")
            self.assertIs(app.focused, search)
            self.assertEqual(search.cursor_position, 1)

    async def test_shift_enter_opens_save_folder_and_exits(self) -> None:
        selected = game("1", "Alpha")
        save_folder = Path("/tmp/1/pfx/drive_c/users/steamuser/Documents/Alpha")
        app = PrefixOpenerApp([selected])

        with (
            patch("prefix_opener.ui.find_save_folder", return_value=save_folder) as find,
            patch("prefix_opener.ui.subprocess.Popen") as popen,
        ):
            async with app.run_test() as pilot:
                await pilot.press("shift+enter")
                await pilot.pause(0.05)

        find.assert_called_once_with(
            selected.app_id,
            selected.compatdata_path,
            selected.library_path,
            selected.name,
        )
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["xdg-open", str(save_folder)])

    async def test_restores_and_reports_theme_changes(self) -> None:
        selected_themes: list[str] = []
        app = PrefixOpenerApp(
            [game("1", "Alpha")],
            theme="textual-light",
            on_theme_change=selected_themes.append,
        )

        async with app.run_test() as pilot:
            self.assertEqual(app.theme, "textual-light")
            selected_themes.clear()
            app.theme = "textual-dark"
            await pilot.pause()

        self.assertEqual(selected_themes, ["textual-dark"])


if __name__ == "__main__":
    unittest.main()

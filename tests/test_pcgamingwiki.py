from __future__ import annotations

import tempfile
import unittest
from os import utime
from pathlib import Path
from unittest.mock import patch

from prefix_opener.pcgamingwiki import (
    lookup_windows_save_paths,
    resolve_save_folder,
    windows_save_paths_from_html,
)

SAVE_SECTION = """
<table id="table-gamedata">
  <tr class="table-gamedata-body-row">
    <th class="table-gamedata-body-system">Windows</th>
    <td class="table-gamedata-body-location">
      <span><abbr>%APPDATA%</abbr>\\Studio\\Game\\&lt;user-id&gt;</span>
      <sup class="reference"><a>[1]</a></sup>
    </td>
  </tr>
  <tr class="table-gamedata-body-row">
    <th class="table-gamedata-body-system">Linux</th>
    <td class="table-gamedata-body-location">$XDG_DATA_HOME/game</td>
  </tr>
</table>
"""


class PCGamingWikiTests(unittest.TestCase):
    def test_extracts_only_windows_save_paths(self) -> None:
        self.assertEqual(
            windows_save_paths_from_html(SAVE_SECTION),
            [r"%APPDATA%\Studio\Game\<user-id>"],
        )

    def test_extracts_steam_save_path_for_fh5(self) -> None:
        section = """
        <tr class="table-gamedata-body-row">
          <th class="table-gamedata-body-system">Steam</th>
          <td class="table-gamedata-body-location"><span>
            &lt;Steam-folder&gt;\\userdata\\&lt;user-id&gt;\\1551360\\remote\\&lt;user-id&gt;
          </span></td>
        </tr>
        """

        self.assertEqual(
            windows_save_paths_from_html(section),
            [r"<Steam-folder>\userdata\<user-id>\1551360\remote\<user-id>"],
        )

    @patch("prefix_opener.pcgamingwiki._request_json")
    def test_looks_up_save_section_by_steam_app_id(self, request_json) -> None:
        request_json.side_effect = [
            {"cargoquery": [{"title": {"Page": "Example Game"}}]},
            {
                "parse": {
                    "sections": [
                        {"line": "Game data", "index": "3"},
                        {"line": "Save game data location", "index": "5"},
                    ]
                }
            },
            {"parse": {"text": {"*": SAVE_SECTION}}},
        ]

        self.assertEqual(
            lookup_windows_save_paths("123"),
            [r"%APPDATA%\Studio\Game\<user-id>"],
        )
        self.assertEqual(request_json.call_args_list[0].args[0]["where"], 'Steam_AppID HOLDS "123"')
        self.assertEqual(request_json.call_args_list[2].args[0]["section"], "5")

    @patch("prefix_opener.pcgamingwiki._request_json")
    def test_falls_back_to_first_game_name_search_result(self, request_json) -> None:
        request_json.side_effect = [
            {"query": {"search": [{"title": "Example Game"}]}},
            {
                "parse": {
                    "sections": [
                        {"line": "Save game data location", "index": "5"}
                    ]
                }
            },
            {"parse": {"text": {"*": SAVE_SECTION}}},
        ]

        self.assertEqual(
            lookup_windows_save_paths("4294967295", "Example Game"),
            [r"%APPDATA%\Studio\Game\<user-id>"],
        )
        search_parameters = request_json.call_args_list[0].args[0]
        self.assertEqual(search_parameters["action"], "query")
        self.assertEqual(search_parameters["srsearch"], "Example Game")
        self.assertEqual(request_json.call_args_list[1].args[0]["page"], "Example Game")

    def test_resolves_variables_and_user_placeholders_inside_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            compatdata = Path(directory) / "123"
            save_folder = (
                compatdata
                / "pfx/drive_c/users/steamuser/AppData/Roaming/Studio/Game/456"
            )
            save_folder.mkdir(parents=True)

            result = resolve_save_folder(
                compatdata, r"%APPDATA%\Studio\Game\<user-id>", "123"
            )

            self.assertEqual(result, save_folder)

    def test_returns_parent_when_wiki_path_is_a_save_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            compatdata = Path(directory) / "123"
            save_folder = compatdata / "pfx/drive_c/users/steamuser/Documents/Game"
            save_folder.mkdir(parents=True)

            result = resolve_save_folder(
                compatdata, r"%USERPROFILE%\Documents\Game\save.dat", "123"
            )

            self.assertEqual(result, save_folder)

    def test_resolves_steam_userdata_save_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            steam_root = Path(directory) / "Steam"
            older_folder = steam_root / "userdata/1234/1551360/remote/1111"
            save_folder = steam_root / "userdata/1234/1551360/remote/5678"
            older_folder.mkdir(parents=True)
            save_folder.mkdir(parents=True)
            utime(older_folder, (1, 1))
            utime(save_folder, (2, 2))

            result = resolve_save_folder(
                Path(directory) / "compatdata/1551360",
                r"<Steam-folder>\userdata\<user-id>\1551360\remote\<user-id>",
                "1551360",
                steam_root,
            )

            self.assertEqual(result, save_folder)

    def test_rejects_paths_outside_the_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            compatdata = Path(directory) / "123"
            (compatdata / "pfx/drive_c").mkdir(parents=True)

            result = resolve_save_folder(
                compatdata, r"%USERPROFILE%\..\..\outside", "123"
            )

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from prefix_opener.steam import (
    discover_prefixes,
    library_paths,
    steam_cache_fingerprint,
)


class SteamDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.steam_root = self.base / "Steam"
        self.extra_library = self.base / "Games"
        (self.steam_root / "steamapps").mkdir(parents=True)
        (self.extra_library / "steamapps" / "compatdata" / "123" / "pfx").mkdir(
            parents=True
        )
        (self.extra_library / "steamapps" / "compatdata" / "not-an-app").mkdir()
        (self.extra_library / "steamapps" / "compatdata" / "456").mkdir()
        (self.extra_library / "steamapps" / "appmanifest_123.acf").write_text(
            '"AppState"\n{\n    "appid" "123"\n    "name" "Test Game"\n}\n',
            encoding="utf-8",
        )
        (self.steam_root / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n    "0"\n    {{\n        "path" "{self.extra_library}"\n    }}\n}}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_library_paths_include_root_and_configured_libraries(self) -> None:
        self.assertEqual(
            library_paths(self.steam_root),
            [self.steam_root.resolve(), self.extra_library.resolve()],
        )

    def test_discovers_only_usable_numeric_prefixes(self) -> None:
        games = discover_prefixes([self.steam_root])

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].app_id, "123")
        self.assertEqual(games[0].name, "Test Game")
        self.assertEqual(
            games[0].prefix_path,
            str(
                (
                    self.extra_library / "steamapps" / "compatdata" / "123" / "pfx"
                ).resolve()
            ),
        )

    def test_cache_fingerprint_changes_when_a_prefix_is_created(self) -> None:
        initial_fingerprint = steam_cache_fingerprint([self.steam_root])
        (self.extra_library / "steamapps" / "compatdata" / "789" / "pfx").mkdir(
            parents=True
        )

        self.assertNotEqual(
            steam_cache_fingerprint([self.steam_root]), initial_fingerprint
        )

    def test_cache_fingerprint_changes_when_a_manifest_changes(self) -> None:
        initial_fingerprint = steam_cache_fingerprint([self.steam_root])
        manifest = self.extra_library / "steamapps" / "appmanifest_123.acf"
        manifest.write_text(
            '"AppState"\n{\n    "appid" "123"\n    "name" "Renamed Game"\n}\n',
            encoding="utf-8",
        )

        self.assertNotEqual(
            steam_cache_fingerprint([self.steam_root]), initial_fingerprint
        )

    def test_uses_fallback_name_when_manifest_is_missing(self) -> None:
        prefix = self.steam_root / "steamapps" / "compatdata" / "789" / "pfx"
        prefix.mkdir(parents=True)

        games = discover_prefixes([self.steam_root])

        unknown = next(game for game in games if game.app_id == "789")
        self.assertEqual(unknown.name, "Unknown game (789)")

    def test_resolves_manifest_from_a_different_library(self) -> None:
        prefix = self.steam_root / "steamapps" / "compatdata" / "321" / "pfx"
        prefix.mkdir(parents=True)
        (self.extra_library / "steamapps" / "appmanifest_321.acf").write_text(
            '"AppState"\n{\n    "appid" "321"\n    "name" "Secondary Game"\n}\n',
            encoding="utf-8",
        )

        games = discover_prefixes([self.steam_root])

        secondary = next(game for game in games if game.app_id == "321")
        self.assertEqual(secondary.name, "Secondary Game")

    def test_resolves_non_steam_name_from_shortcuts(self) -> None:
        app_id = 3_456_789_012
        prefix = self.steam_root / "steamapps" / "compatdata" / str(app_id) / "pfx"
        prefix.mkdir(parents=True)
        shortcuts = self.steam_root / "userdata" / "1" / "config" / "shortcuts.vdf"
        shortcuts.parent.mkdir(parents=True)
        shortcuts.write_bytes(
            b"\x00shortcuts\x00"
            b"\x000\x00"
            + b"\x02appid\x00"
            + struct.pack("<I", app_id)
            + b"\x01AppName\x00Non-Steam Game\x00"
            + b"\x08\x08\x08"
        )

        games = discover_prefixes([self.steam_root])

        shortcut = next(game for game in games if game.app_id == str(app_id))
        self.assertEqual(shortcut.name, "Non-Steam Game")

    def test_resolves_historical_non_steam_name_from_screenshots(self) -> None:
        app_id = 2_299_438_711
        prefix = self.steam_root / "steamapps" / "compatdata" / str(app_id) / "pfx"
        prefix.mkdir(parents=True)
        screenshots = self.steam_root / "userdata" / "1" / "760" / "screenshots.vdf"
        screenshots.parent.mkdir(parents=True)
        shortcut_game_id = (app_id << 32) | 0x02000000
        screenshots.write_text(
            '"screenshots"\n{\n'
            '    "shortcutnames"\n    {\n'
            f'        "{shortcut_game_id}" "MiSide"\n'
            "    }\n}\n",
            encoding="utf-8",
        )

        games = discover_prefixes([self.steam_root])

        historical = next(game for game in games if game.app_id == str(app_id))
        self.assertEqual(historical.name, "MiSide")

    def test_resolves_removed_manifest_from_appinfo_cache(self) -> None:
        app_id = 1_151_640
        prefix = self.steam_root / "steamapps" / "compatdata" / str(app_id) / "pfx"
        prefix.mkdir(parents=True)

        strings = ["appinfo", "common", "name"]
        binary_vdf = (
            b"\x00"
            + struct.pack("<I", 0)
            + b"\x00"
            + struct.pack("<I", 1)
            + b"\x01"
            + struct.pack("<I", 2)
            + b"Cached Steam Game\x00\x08\x08\x08"
        )
        metadata = bytes(60)
        entry = (
            struct.pack("<II", app_id, len(metadata) + len(binary_vdf))
            + metadata
            + binary_vdf
        )
        string_table_offset = 16 + len(entry) + 4
        string_table = struct.pack("<I", len(strings)) + b"".join(
            value.encode() + b"\x00" for value in strings
        )
        appinfo = self.steam_root / "appcache" / "appinfo.vdf"
        appinfo.parent.mkdir()
        appinfo.write_bytes(
            struct.pack("<IIQ", 0x07564429, 1, string_table_offset)
            + entry
            + struct.pack("<I", 0)
            + string_table
        )

        games = discover_prefixes([self.steam_root])

        cached = next(game for game in games if game.app_id == str(app_id))
        self.assertEqual(cached.name, "Cached Steam Game")


if __name__ == "__main__":
    unittest.main()

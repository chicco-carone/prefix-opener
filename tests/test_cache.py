from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prefix_opener.cache import (
    clear_cache,
    load_cache,
    load_theme,
    save_cache,
    save_theme,
)
from prefix_opener.steam import GamePrefix


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.cache_path = self.base / "cache" / "games.json"
        self.prefix_path = self.base / "prefix"
        self.prefix_path.mkdir()
        self.game = GamePrefix(
            app_id="123",
            name="Test Game",
            prefix_path=str(self.prefix_path),
            compatdata_path=str(self.base),
            library_path=str(self.base),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_cache_round_trip_with_matching_scope(self) -> None:
        save_cache([self.game], self.cache_path, scope=["/steam"])

        self.assertEqual(
            load_cache(self.cache_path, scope=["/steam"]),
            [self.game],
        )

    def test_cache_is_ignored_for_different_scope(self) -> None:
        save_cache([self.game], self.cache_path, scope=["/steam"])

        self.assertIsNone(load_cache(self.cache_path, scope=None))

    def test_cache_is_ignored_when_steam_sources_change(self) -> None:
        save_cache([self.game], self.cache_path, source_fingerprint="original")

        self.assertIsNone(
            load_cache(self.cache_path, source_fingerprint="changed")
        )

    def test_missing_prefix_is_removed_from_cached_results(self) -> None:
        save_cache([self.game], self.cache_path)
        self.prefix_path.rmdir()

        self.assertEqual(load_cache(self.cache_path), [])

    def test_invalid_cache_is_ignored(self) -> None:
        self.cache_path.parent.mkdir()
        self.cache_path.write_text("[]", encoding="utf-8")

        self.assertIsNone(load_cache(self.cache_path))

    def test_clear_cache_reports_whether_file_was_removed(self) -> None:
        save_cache([self.game], self.cache_path)

        self.assertTrue(clear_cache(self.cache_path))
        self.assertFalse(clear_cache(self.cache_path))

    def test_theme_round_trip(self) -> None:
        save_cache([self.game], self.cache_path)

        save_theme("nord", self.cache_path)

        self.assertEqual(load_theme(self.cache_path), "nord")

    def test_game_cache_refresh_preserves_theme(self) -> None:
        save_cache([self.game], self.cache_path)
        save_theme("textual-light", self.cache_path)

        save_cache([self.game], self.cache_path, scope=["/steam"])

        self.assertEqual(load_theme(self.cache_path), "textual-light")


if __name__ == "__main__":
    unittest.main()

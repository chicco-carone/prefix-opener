from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .steam import GamePrefix

CACHE_VERSION = 4


def default_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base / "prefix-opener" / "games.json"


def load_cache(
    path: Path | None = None,
    *,
    scope: list[str] | None = None,
    source_fingerprint: str | None = None,
) -> list[GamePrefix] | None:
    cache_path = path or default_cache_path()
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            payload.get("version") != CACHE_VERSION
            or payload.get("scope") != scope
            or payload.get("source_fingerprint") != source_fingerprint
        ):
            return None
        games = [GamePrefix.from_dict(item) for item in payload["games"]]
    except (
        AttributeError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    return [game for game in games if Path(game.prefix_path).is_dir()]


def save_cache(
    games: list[GamePrefix],
    path: Path | None = None,
    *,
    scope: list[str] | None = None,
    source_fingerprint: str | None = None,
) -> None:
    cache_path = path or default_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "created_at": time.time(),
        "scope": scope,
        "source_fingerprint": source_fingerprint,
        "games": [game.to_dict() for game in games],
    }
    if theme := load_theme(cache_path):
        payload["theme"] = theme
    _write_payload(cache_path, payload)


def load_theme(path: Path | None = None) -> str | None:
    cache_path = path or default_cache_path()
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        theme = payload.get("theme")
    except (AttributeError, OSError, json.JSONDecodeError):
        return None
    return theme if isinstance(theme, str) and theme else None


def save_theme(theme: str, path: Path | None = None) -> None:
    cache_path = path or default_cache_path()
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    payload["theme"] = theme
    _write_payload(cache_path, payload)


def _write_payload(cache_path: Path, payload: dict[str, object]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(cache_path)


def clear_cache(path: Path | None = None) -> bool:
    cache_path = path or default_cache_path()
    try:
        cache_path.unlink()
    except FileNotFoundError:
        return False
    return True

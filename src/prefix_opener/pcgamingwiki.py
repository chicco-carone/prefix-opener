from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .steam import default_steam_roots

_API_URL = "https://www.pcgamingwiki.com/w/api.php"
_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
_WINDOWS_ROOTS = (
    ("%PROGRAMFILES(X86)%", "Program Files (x86)"),
    ("%LOCALAPPDATA%", "users/steamuser/AppData/Local"),
    ("%USERPROFILE%", "users/steamuser"),
    ("%PROGRAMFILES%", "Program Files"),
    ("%PROGRAMDATA%", "ProgramData"),
    ("%SYSTEMROOT%", "windows"),
    ("%SAVEDGAMES%", "users/steamuser/Saved Games"),
    ("%APPDATA%", "users/steamuser/AppData/Roaming"),
    ("%PUBLIC%", "users/Public"),
    ("%WINDIR%", "windows"),
)


class PCGamingWikiError(RuntimeError):
    pass


class _SavePathParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []
        self._in_row = False
        self._field: str | None = None
        self._system: list[str] = []
        self._location: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        class_names = set(classes.split())
        if tag == "tr" and "table-gamedata-body-row" in class_names:
            self._in_row = True
            self._system = []
            self._location = []
        if not self._in_row:
            return
        if self._ignored_depth:
            self._ignored_depth += 1
            return
        if "reference" in class_names:
            self._ignored_depth = 1
        elif "table-gamedata-body-system" in class_names:
            self._field = "system"
        elif "table-gamedata-body-location" in class_names:
            self._field = "location"
        elif tag == "br" and self._field == "location":
            self._location.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag in ("th", "td"):
            self._field = None
        if tag == "tr" and self._in_row:
            system = "".join(self._system).strip().casefold()
            if system == "steam" or system.startswith("windows"):
                self.paths.extend(
                    path.strip()
                    for path in "".join(self._location).splitlines()
                    if path.strip()
                )
            self._in_row = False
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._field == "system":
            self._system.append(data)
        elif self._field == "location":
            self._location.append(data)


def windows_save_paths_from_html(section_html: str) -> list[str]:
    parser = _SavePathParser()
    parser.feed(section_html)
    return parser.paths


def _request_json(parameters: dict[str, str]) -> dict[str, Any]:
    url = f"{_API_URL}?{urlencode(parameters)}"
    request = Request(url, headers={"User-Agent": "prefix-opener/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise PCGamingWikiError(f"PCGamingWiki request failed: {error}") from error
    if not isinstance(result, dict):
        raise PCGamingWikiError("PCGamingWiki returned an invalid response")
    if "error" in result:
        raise PCGamingWikiError("PCGamingWiki returned an API error")
    return result


def lookup_windows_save_paths(app_id: str, game_name: str | None = None) -> list[str]:
    is_non_steam = app_id.isdigit() and int(app_id) >= 1 << 31
    page: object | None = None
    if not is_non_steam:
        page_result = _request_json(
            {
                "action": "cargoquery",
                "tables": "Infobox_game",
                "fields": "_pageName=Page",
                "where": f'Steam_AppID HOLDS "{app_id}"',
                "limit": "1",
                "format": "json",
            }
        )
        try:
            page = page_result["cargoquery"][0]["title"]["Page"]
        except (KeyError, IndexError, TypeError):
            pass
    if page is None:
        if not game_name:
            raise PCGamingWikiError("No PCGamingWiki page found for this game")
        search_result = _request_json(
            {
                "action": "query",
                "list": "search",
                "srsearch": game_name,
                "srnamespace": "0",
                "srlimit": "1",
                "format": "json",
            }
        )
        try:
            page = search_result["query"]["search"][0]["title"]
        except (KeyError, IndexError, TypeError) as error:
            raise PCGamingWikiError(
                f'No PCGamingWiki page found for "{game_name}"'
            ) from error
    if not isinstance(page, str):
        raise PCGamingWikiError("PCGamingWiki returned an invalid page name")

    sections_result = _request_json(
        {"action": "parse", "page": page, "prop": "sections", "format": "json"}
    )
    try:
        sections = sections_result["parse"]["sections"]
        section_index = next(
            section["index"]
            for section in sections
            if section.get("line", "").casefold() == "save game data location"
        )
    except (KeyError, StopIteration, TypeError) as error:
        raise PCGamingWikiError(
            "PCGamingWiki has no save location for this game"
        ) from error

    section_result = _request_json(
        {
            "action": "parse",
            "page": page,
            "section": str(section_index),
            "prop": "text",
            "format": "json",
        }
    )
    try:
        section_html = section_result["parse"]["text"]["*"]
    except (KeyError, TypeError) as error:
        raise PCGamingWikiError(
            "PCGamingWiki returned invalid save location data"
        ) from error
    if not isinstance(section_html, str):
        raise PCGamingWikiError("PCGamingWiki returned invalid save location data")

    paths = windows_save_paths_from_html(section_html)
    if not paths:
        raise PCGamingWikiError(
            "PCGamingWiki has no supported save location for this game"
        )
    return paths


def _path_pattern(
    compatdata_path: Path,
    reported_path: str,
    app_id: str,
    steam_path: Path | None,
) -> tuple[Path, str] | None:
    drive_c = compatdata_path / "pfx" / "drive_c"
    normalized = reported_path.replace("\\", "/").strip().replace("\u200b", "")
    folded = normalized.casefold()

    relative: str | None = None
    root = drive_c
    steam_variable = "<steam-folder>"
    if folded.startswith(steam_variable) and steam_path is not None:
        root = steam_path
        relative = normalized[len(steam_variable) :].lstrip("/")
    elif folded.startswith("c:/"):
        relative = normalized[3:]
    else:
        for variable, windows_root in _WINDOWS_ROOTS:
            if folded.startswith(variable.casefold()):
                relative = f"{windows_root}/{normalized[len(variable) :].lstrip('/')}"
                break
    if relative is None:
        return None

    relative = re.sub(r"<app(?:lication)?-?id>", app_id, relative, flags=re.IGNORECASE)
    relative = _PLACEHOLDER_RE.sub("*", relative)
    parts = [part for part in relative.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return root, "/".join(parts)


def resolve_save_folder(
    compatdata_path: str | Path,
    reported_path: str,
    app_id: str,
    steam_path: str | Path | None = None,
) -> Path | None:
    pattern = _path_pattern(
        Path(compatdata_path),
        reported_path,
        app_id,
        Path(steam_path) if steam_path is not None else None,
    )
    if pattern is None:
        return None
    root_path, relative = pattern
    try:
        if "*" in relative:
            candidates = list(root_path.glob(relative))
            candidates.sort(
                key=lambda candidate: candidate.stat().st_mtime_ns, reverse=True
            )
        else:
            candidates = [root_path / relative]
        root = root_path.resolve(strict=False)
        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(root):
                continue
            if resolved.is_dir():
                return resolved
            if resolved.is_file():
                return resolved.parent
        candidate = (root_path / relative).resolve(strict=False)
        if "*" not in relative and candidate.suffix and candidate.parent.is_dir():
            return candidate.parent
    except OSError:
        return None
    return None


def find_save_folder(
    app_id: str,
    compatdata_path: str | Path,
    library_path: str | Path,
    game_name: str | None = None,
) -> Path:
    reported_paths = lookup_windows_save_paths(app_id, game_name)
    steam_paths = [Path(library_path), *default_steam_roots()]
    for reported_path in reported_paths:
        if reported_path.casefold().startswith("<steam-folder>"):
            for steam_path in dict.fromkeys(steam_paths):
                if folder := resolve_save_folder(
                    compatdata_path, reported_path, app_id, steam_path
                ):
                    return folder
        elif folder := resolve_save_folder(compatdata_path, reported_path, app_id):
            return folder
    raise PCGamingWikiError("The reported save folder does not exist in this prefix")

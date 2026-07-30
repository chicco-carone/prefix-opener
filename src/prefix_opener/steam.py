from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_VDF_VALUE = r'"((?:\\.|[^"\\])*)"'
_LIBRARY_PATH_RE = re.compile(rf'"path"\s*{_VDF_VALUE}', re.IGNORECASE)
_GAME_NAME_RE = re.compile(rf'"name"\s*{_VDF_VALUE}', re.IGNORECASE)
_SHORTCUT_NAMES_RE = re.compile(
    r'"shortcutnames"\s*\{(?P<body>.*?)\}', re.IGNORECASE | re.DOTALL
)
_SHORTCUT_NAME_RE = re.compile(rf'"(\d+)"\s*{_VDF_VALUE}')


@dataclass(frozen=True, slots=True)
class GamePrefix:
    app_id: str
    name: str
    prefix_path: str
    compatdata_path: str
    library_path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> GamePrefix:
        fields = ("app_id", "name", "prefix_path", "compatdata_path", "library_path")
        if not all(isinstance(data.get(field), str) for field in fields):
            raise ValueError("Invalid cached game entry")
        return cls(**{field: data[field] for field in fields})  # type: ignore[arg-type]


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _decode_vdf(value: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            if escaped in ('"', "\\"):
                decoded.append(escaped)
                index += 2
                continue
        decoded.append(value[index])
        index += 1
    return "".join(decoded)


def default_steam_roots() -> list[Path]:
    candidates = _default_steam_root_candidates()
    roots: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        if root.is_dir() and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _default_steam_root_candidates() -> list[Path]:
    return [
        _resolved(candidate)
        for candidate in (
            Path("~/.local/share/Steam"),
            Path("~/.steam/steam"),
            Path("~/.steam/root"),
            Path("~/.var/app/com.valvesoftware.Steam/.local/share/Steam"),
        )
    ]


def library_paths(steam_root: Path) -> list[Path]:
    root = _resolved(steam_root)
    paths = [root]
    config_path = root / "steamapps" / "libraryfolders.vdf"
    try:
        config = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        config = ""

    for match in _LIBRARY_PATH_RE.finditer(config):
        paths.append(_resolved(Path(_decode_vdf(match.group(1)))))

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def steam_cache_fingerprint(steam_roots: list[Path] | None = None) -> str:
    roots = default_steam_roots() if steam_roots is None else steam_roots
    sources = set(_default_steam_root_candidates() if steam_roots is None else roots)

    libraries: set[Path] = set()
    for steam_root in roots:
        root = _resolved(steam_root)
        sources.update(
            {
                root / "steamapps" / "libraryfolders.vdf",
                root / "appcache" / "appinfo.vdf",
                root / "userdata",
            }
        )
        libraries.update(library_paths(root))

        userdata = root / "userdata"
        try:
            users = list(userdata.iterdir())
        except OSError:
            users = []
        for user in users:
            if not user.is_dir():
                continue
            sources.update(
                {
                    user,
                    user / "config",
                    user / "config" / "shortcuts.vdf",
                    user / "760",
                    user / "760" / "screenshots.vdf",
                }
            )

    for library in libraries:
        steamapps = library / "steamapps"
        compatdata_root = steamapps / "compatdata"
        sources.update({steamapps, compatdata_root})
        try:
            sources.update(steamapps.glob("appmanifest_*.acf"))
            compatdata_entries = list(compatdata_root.iterdir())
        except OSError:
            compatdata_entries = []
        for compatdata in compatdata_entries:
            if compatdata.name.isdigit() and compatdata.is_dir():
                sources.update({compatdata, compatdata / "pfx"})

    digest = hashlib.sha256()
    for source in sorted(sources, key=str):
        digest.update(str(source).encode(errors="surrogateescape"))
        digest.update(b"\0")
        try:
            stat = source.stat()
        except OSError:
            digest.update(b"missing\0")
        else:
            digest.update(f"{stat.st_mtime_ns}\0{stat.st_size}\0".encode())
    return digest.hexdigest()


def _manifest_name(manifest: Path) -> str | None:
    try:
        contents = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _GAME_NAME_RE.search(contents)
    if not match:
        return None
    return _decode_vdf(match.group(1))


class _BinaryVdfReader:
    def __init__(
        self,
        data: bytes,
        position: int = 0,
        string_table: list[str] | None = None,
    ) -> None:
        self.data = data
        self.position = position
        self.string_table = string_table

    def read_object(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.position < len(self.data):
            value_type = self._read(1)[0]
            if value_type == 8:
                return result
            key = self._read_key()
            if value_type == 0:
                value: Any = self.read_object()
            elif value_type == 1:
                value = self._read_string()
            elif value_type == 2:
                value = struct.unpack("<I", self._read(4))[0]
            elif value_type == 3:
                value = struct.unpack("<f", self._read(4))[0]
            elif value_type == 4:
                value = struct.unpack("<I", self._read(4))[0]
            elif value_type == 5:
                value = self._read_wide_string()
            elif value_type == 6:
                value = self._read(4)
            elif value_type == 7:
                value = struct.unpack("<Q", self._read(8))[0]
            elif value_type == 10:
                value = struct.unpack("<q", self._read(8))[0]
            else:
                raise ValueError(f"Unsupported binary VDF type: {value_type}")
            result[key] = value
        return result

    def _read_key(self) -> str:
        if self.string_table is None:
            return self._read_string()
        index = struct.unpack("<I", self._read(4))[0]
        try:
            return self.string_table[index]
        except IndexError as error:
            raise ValueError("Invalid binary VDF string table index") from error

    def _read(self, length: int) -> bytes:
        end = self.position + length
        if end > len(self.data):
            raise ValueError("Unexpected end of binary VDF")
        value = self.data[self.position : end]
        self.position = end
        return value

    def _read_string(self) -> str:
        end = self.data.find(b"\0", self.position)
        if end == -1:
            raise ValueError("Unterminated binary VDF string")
        value = self.data[self.position : end].decode("utf-8", errors="replace")
        self.position = end + 1
        return value

    def _read_wide_string(self) -> str:
        start = self.position
        while self.position + 1 < len(self.data):
            if self.data[self.position : self.position + 2] == b"\0\0":
                value = self.data[start : self.position].decode(
                    "utf-16-le", errors="replace"
                )
                self.position += 2
                return value
            self.position += 2
        raise ValueError("Unterminated binary VDF wide string")


def _shortcut_names(steam_roots: list[Path]) -> dict[str, str]:
    names = _historical_shortcut_names(steam_roots)
    for steam_root in steam_roots:
        userdata = _resolved(steam_root) / "userdata"
        try:
            shortcut_files = list(userdata.glob("*/config/shortcuts.vdf"))
        except OSError:
            continue
        for shortcut_file in shortcut_files:
            try:
                root = _BinaryVdfReader(shortcut_file.read_bytes()).read_object()
            except (OSError, ValueError):
                continue
            shortcuts = root.get("shortcuts")
            if not isinstance(shortcuts, dict):
                continue
            for shortcut in shortcuts.values():
                if not isinstance(shortcut, dict):
                    continue
                fields = {key.casefold(): value for key, value in shortcut.items()}
                app_id = fields.get("appid")
                name = fields.get("appname")
                if isinstance(app_id, int) and isinstance(name, str) and name:
                    names[str(app_id)] = name
    return names


def _historical_shortcut_names(steam_roots: list[Path]) -> dict[str, str]:
    names: dict[str, str] = {}
    for steam_root in steam_roots:
        userdata = _resolved(steam_root) / "userdata"
        try:
            screenshot_files = list(userdata.glob("*/760/screenshots.vdf"))
        except OSError:
            continue
        for screenshot_file in screenshot_files:
            try:
                contents = screenshot_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            section = _SHORTCUT_NAMES_RE.search(contents)
            if not section:
                continue
            for match in _SHORTCUT_NAME_RE.finditer(section.group("body")):
                shortcut_game_id = int(match.group(1))
                app_id = shortcut_game_id >> 32
                if app_id:
                    names[str(app_id)] = _decode_vdf(match.group(2))
    return names


def _appinfo_names(steam_roots: list[Path], app_ids: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    numeric_ids = {int(app_id) for app_id in app_ids}
    for steam_root in steam_roots:
        appinfo_path = _resolved(steam_root) / "appcache" / "appinfo.vdf"
        try:
            data = appinfo_path.read_bytes()
            magic, _universe = struct.unpack_from("<II", data)
        except (OSError, struct.error):
            continue

        version = magic & 0xFF
        if magic >> 8 != 0x075644 or version not in (39, 40, 41):
            continue

        position = 8
        string_table: list[str] | None = None
        if version >= 41:
            try:
                string_table_offset = struct.unpack_from("<Q", data, position)[0]
                position += 8
                string_reader = _BinaryVdfReader(data, string_table_offset)
                string_count = struct.unpack("<I", string_reader._read(4))[0]
                string_table = [
                    string_reader._read_string() for _ in range(string_count)
                ]
            except (ValueError, struct.error):
                continue

        while position + 8 <= len(data):
            app_id, size = struct.unpack_from("<II", data, position)
            position += 8
            if app_id == 0:
                break
            end = position + size
            metadata_size = 60 if version >= 40 else 40
            data_position = position + metadata_size
            if end > len(data) or data_position > end:
                break
            if app_id in numeric_ids:
                try:
                    app_data = _BinaryVdfReader(
                        data, data_position, string_table
                    ).read_object()
                    appinfo = app_data.get("appinfo", app_data)
                    common = (
                        appinfo.get("common") if isinstance(appinfo, dict) else None
                    )
                    name = common.get("name") if isinstance(common, dict) else None
                    if isinstance(name, str) and name:
                        names[str(app_id)] = name
                except ValueError:
                    pass
            position = end
    return names


def _game_names(libraries: list[Path], steam_roots: list[Path]) -> dict[str, str]:
    names = _shortcut_names(steam_roots)
    for library in libraries:
        try:
            manifests = list((library / "steamapps").glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            app_id = manifest.stem.removeprefix("appmanifest_")
            if app_id.isdigit() and (name := _manifest_name(manifest)):
                names[app_id] = name
    return names


def discover_prefixes(steam_roots: list[Path] | None = None) -> list[GamePrefix]:
    roots = default_steam_roots() if steam_roots is None else steam_roots
    libraries: list[Path] = []
    seen_libraries: set[Path] = set()
    for steam_root in roots:
        for library in library_paths(steam_root):
            if library not in seen_libraries:
                seen_libraries.add(library)
                libraries.append(library)

    prefixes: list[tuple[Path, Path, Path]] = []
    seen_prefixes: set[Path] = set()

    for library in libraries:
        compatdata_root = library / "steamapps" / "compatdata"
        try:
            entries = list(compatdata_root.iterdir())
        except OSError:
            continue

        for compatdata in entries:
            if not compatdata.name.isdigit() or not compatdata.is_dir():
                continue
            prefix = _resolved(compatdata / "pfx")
            if not prefix.is_dir() or prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            library = _resolved(library)
            prefixes.append((library, _resolved(compatdata), prefix))

    names = _game_names(libraries, roots)
    missing_app_ids = {
        compatdata.name for _, compatdata, _ in prefixes if compatdata.name not in names
    }
    names.update(_appinfo_names(roots, missing_app_ids))
    games = [
        GamePrefix(
            app_id=compatdata.name,
            name=names.get(compatdata.name, f"Unknown game ({compatdata.name})"),
            prefix_path=str(prefix),
            compatdata_path=str(compatdata),
            library_path=str(library),
        )
        for library, compatdata, prefix in prefixes
    ]

    return sorted(games, key=lambda game: (game.name.casefold(), int(game.app_id)))

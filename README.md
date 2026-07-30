# Steam Prefix Opener

A small Linux TUI that finds Steam games with Proton prefixes, lets you search
by game name, AppID, or path, and opens the selected prefix with `xdg-open`.

The scanner reads `libraryfolders.vdf`, indexes manifests across every Steam
library, reads current non-Steam names from each user's binary `shortcuts.vdf`,
recovers historical shortcut names from `screenshots.vdf`, and falls back to
Steam's binary `appcache/appinfo.vdf`. It checks every `steamapps/compatdata`
directory and resolves symlinks before storing paths. This also handles prefixes
on one drive whose game manifest is stored on another drive.

## Run

```bash
uv run prefix-opener
```

Type to filter the game list and press Enter to open the first highlighted
prefix. You can also move through the results and press Enter. Press Shift+Enter
to look up the game's Windows save location on PCGamingWiki and open the
corresponding folder in its Proton prefix. Non-Steam shortcuts fall back to the
first PCGamingWiki search result for their configured game name. Press Escape to
quit, `/` to return focus to the search field, and `t` to select a theme. The
selected theme is restored on the next run.

The first run scans Steam and writes results to
`$XDG_CACHE_HOME/prefix-opener/games.json` (or
`~/.cache/prefix-opener/games.json`). Later runs load that cache while Steam's
libraries, prefixes, manifests, and shortcut metadata remain unchanged.

Force a rescan if Steam changed while the opener was running:

```bash
uv run prefix-opener --refresh
```

Scan a non-standard Steam installation (repeat the option if needed):

```bash
uv run prefix-opener --steam-root /path/to/Steam
```

Remove cached results:

```bash
uv run prefix-opener --clear-cache
```

## Install

Install the command for the current user with uv:

```bash
uv tool install .
prefix-opener
```

On Arch Linux, build and install the package from the repository:

```bash
cd packaging/arch
makepkg -si
```

## Test

```bash
uv run python -m unittest discover -s tests
```

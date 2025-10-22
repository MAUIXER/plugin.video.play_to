## Quick orientation

This is a Kodi video addon written in Python targeting Kodi 22+. Key entry points and components:

- `main.py` — addon entry; builds `params_str` from `sys.argv` and calls `plugin.router(params_str)`.
- `resources/lib/plugin.py` — the heart of the addon: router, metadata flows, cache helpers, and playback resolution.
- `resources/lib/prehrajto.py` — site-specific scraping/resolving for Prehraj.to (stream discovery + direct links).
- `resources/lib/tmdb.py` & `resources/lib/tmdb_account.py` — TMDB API wrapper and account helpers.
- `resources/lib/utils.py` — common helpers (notably `clean_title_for_tmdb`, `get_url`, `log`, `encode`).

Read these files together to understand data flow: UI -> router -> metadata acquisition (TMDB/CSFD) -> `find_sources` -> `resolve_video` -> `xbmcplugin.setResolvedUrl()`.

## Architecture & patterns an agent should follow

- "Metadata-first": the addon prefers to collect a full `meta` JSON bundle (TMDB id, title, year, art, IDs) and pass it between actions. Preserve and pass `meta` when listing or resolving.
- Two user flows are supported: metadata-driven (catalog → find_sources → resolve) and query-driven (free text → `clean_title_for_tmdb` → TMDB search → find_sources).
- Router model: actions are encoded in the plugin URL `?action=...` and dispatched by `plugin.router(paramstring)`; construct URLs that include `action` and `meta` when navigating.

## Project-specific conventions

- Settings keys are used liberally (see `resources/settings.xml`). Common IDs to reference: `api_key`, `tmdb_cache_ttl`, `playback_dir`, `history_dir`, `shared_cache_path`, `ip_cache_dir`, `ls`, `max_pages`, `search_ls`, `search_pages`, `enable_trakt_scrobbling`.
- File paths use `xbmcvfs.translatePath()` and `special://` locations. Use `xbmcvfs` helpers when working with files.
- Caching is done via `load_cache(name, ttl)` / `save_cache(name, data)` — TTL is configured by settings and the cache root is created via `_get_cache_dir()`.
- Logging uses the project's `log()` wrapper and message prefixes like `PLAY.TO * DEBUG|INFO|ERROR` — searching Kodi logs for `PLAY.TO` is the fastest way to follow runtime behavior.

## Integration points & external dependencies

- TMDB: calls are wrapped in `tmdb_fetch` / `TMDB` client. The TMDB API key is stored in settings `api_key`.
- Prehraj.to: site scraping and HTML parsing live in `prehrajto.py`; `BeautifulSoup` and `regex` extract JS-embedded stream URLs.
- Optional integrations: `trakt` (scrobbling), `csfd` (Czech metadata). Addon manifest (`addon.xml`) declares dependencies on `script.module.requests` and `script.module.beautifulsoup4`.

## Developer workflows & quick commands

- Runtime debugging: run inside Kodi and monitor Kodi log (or use a Log Viewer addon). Filter logs for `PLAY.TO` prefixes.
- Local quick-run (for small router experiments) — emulate Kodi argv (Python must have access to xbmc stubs or run inside Kodi environment):

```bash
python3 -c "import sys; sys.argv=['main.py','1','?action=menu']; import main"
```

- To run static analysis or import checks outside Kodi, install runtime deps:

```bash
pip install requests beautifulsoup4
```

Note: `xbmc`, `xbmcgui`, `xbmcplugin`, and `xbmcvfs` are only available inside Kodi. For unit testing, stub these modules or run tests inside a Kodi dev environment.

## Examples and places to look when changing behavior

- If modifying how links are resolved, edit `resources/lib/prehrajto.py` and `resolve_video` in `resources/lib/plugin.py`.
- If changing metadata matching/normalization, edit `clean_title_for_tmdb` in `resources/lib/utils.py` and TMDB query flow in `resources/lib/tmdb.py`.
- If adding settings, update `resources/settings.xml` and reference the setting ID via `addon.getSetting('<id>')`.

## Short checklist for PR reviewers / agents

- Preserve the `meta` JSON bundle between screens.
- Use `xbmcvfs` for any filesystem interactions and `xbmc` logging via the local `log()` wrapper.
- Respect addon settings for caching and view modes (see `VIEW_MODES` mapping in `plugin.py`).

If any of the above points are unclear or you want more examples (router shapes, `meta` JSON schema examples, or unit-test stubs for `xbmc`), tell me which area to expand. 

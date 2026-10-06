# WRSR Mod Installer: how the code fits together

A PyQt5 desktop app for Workers & Resources: Soviet Republic. It lists mods in the game's `media_soviet/workshop_wip` folder, writes an Owner ID into their `workshopconfig.ini`, and downloads mods (plus the mods they need) from the Skymods catalogue.

`mod_installer.py` only starts the app; everything else is in the `wrsr_installer` package.

## Layers

```
ui/ (Qt widgets)           pages, theme, widgets: no file or network access of their own
   │ signals / callbacks
app_state.py, download_queue.py   shared state and the download queue (QObjects)
   │ run_task() on QThreadPool
workshop.py  archive.py  skymods.py  downloader.py  cache.py   plain Python, no Qt
```

Everything slow (scanning, network, extracting, writing files) runs through `tasks.run_task`, which runs a function on the shared thread pool and delivers its result, error, progress or cancellation on the GUI thread. Tasks stay referenced until their last signal arrives, and every task gets a `CancelToken` (`cancel.py`).

## Modules

| Module | Responsibility |
|---|---|
| `workshop.py` | Parse `workshopconfig.ini` (`$ITEM_ID`, `$OWNER_ID`, `$ITEM_TYPE`, `$ITEM_NAME`, `$ITEM_DESC`), detect its encoding (UTF-8 ± BOM, cp1251, Latin-1) so edits round-trip byte-for-byte, rewrite only the `$OWNER_ID` line, scan the workshop folder, and answer "is this installed?" by Steam ID or exact name (`InstalledIndex`). |
| `archive.py` | Unpack a ZIP, find the folder holding `workshopconfig.ini` at any depth, name the install folder after `$ITEM_ID`, and install with a backup-and-swap so a failed replace restores the old copy. Uses `shutil.move`, so the temp folder may be on another drive. |
| `skymods.py` | Search catalogue.smods.ru (app 784150), parse result pages and mod pages, sanitize descriptions to a small HTML allowlist, and turn network failures into readable `SkymodsError`s. |
| `downloader.py` | Downloads with progress and cancel. modsbase.com pages are handled as a visitor would, in plain HTTP: open the page, wait out its countdown (`data-total`), submit its download form, then save the file from the link (or file) that comes back. Anything unexpected raises `ManualDownloadRequired` with the page URL, so the user can finish in a browser. That covers an error status (including Cloudflare's bot check), no download form, and no file link. The result is checked to be a ZIP and not an error page. |
| `download_queue.py` | The queue model: one download at a time, plus the mods each one needs. A required mod gets its row (a "placeholder") as soon as its name is known: at once if the mod's page was already loaded, otherwise when it loads. It then fills in from a lookup by Steam ID; lookups run in parallel. The mod's own page is opened only when its listing says it needs others (or has no download link). Requirements that are installed are noted instead of queued; already-queued ones aren't added twice; ones Skymods lacks become failed rows. Rows go ahead of the mod if it hasn't started, otherwise right after it. Supports cancel, retry, remove, and a summary once downloads and lookups are done. |
| `cache.py` | `PageCache`: Skymods pages saved on disk (gzip JSON, atomic writes), with their age, pruned at startup (7 days, 400 pages). Any read or write problem just means "not saved". |
| `services.py` | Connects the queue to the real Skymods and download functions and to the game folder: `make_installer` (download, unpack, install), `load_requirements` (a mod's page) and `look_up` (a mod by Steam ID). |
| `app_state.py` | Settings (via `config.py`), the scanned mod list, Owner ID changes with per-mod error reporting, and stale-scan protection. |
| `config.py` | Loads and saves `~/.wrsr_mod_installer_config.json` (same file and keys as version 1). |
| `ui/` | `main_window.py` (sidebar, pages, toasts, quit guard), `library_page.py`, `browse_page.py`, `downloads_page.py`, `settings_page.py`, `install_dialog.py`, `widgets.py` (toasts, banners, pills, async images), `theme.py` (dark palette and stylesheet), `icons.py` (SVG line icons), `text.py` (BBCode to safe HTML), `dialogs.py` (confirmations, dark title bar). |

## Behaviour worth knowing

- **Skymods is slow, unpredictably.** Measured on one day: the same kinds of uncached pages took 1–2 s at some times and 15–62 s at others, whatever the user agent. Its Cloudflare cache keeps searches for 5 minutes and never keeps mod pages, so the app keeps its own copies:
  - **Reuse:** `skymods.get_html(fresh_for=…)` reuses saved pages. That's 10 minutes for searches, and 1 day for mod pages and Steam ID lookups.
  - **Instant display:** the Browse page shows saved results and saved mod pages immediately and refreshes older ones in the background (`saved_search`, `saved_mod`). When merging an older copy into a fresh listing, only gaps are filled (`fill_from`), so fresh download links win.
  - **Timeouts:** the read timeout is 120 s, and the UI shows how long it has waited.
  - **Searching:** searches load one page at a time ("Load more"). A new search or Stop makes the UI ignore the old request's result immediately.
- **Owner IDs are applied manually after downloads.** Version 1.0 removed the per-download prompt so batch downloads aren't interrupted; the Library shows which mods still need it.
- **Nothing is deleted before the user confirms.** The ZIP install previews the mod first. Replacing a mod keeps the old copy until the new one is in place.

## Tests

`python -m pytest` runs the suite (pytest + pytest-qt; Qt runs off-screen):

- Core logic: config parsing and editing, encodings, archive layouts, safe replace, cross-drive moves, Skymods parsing (fixtures in `tests/fixtures` mirror the real markup with made-up content), timeouts and HTTP errors (local test server), downloads with progress and cancel.
- modsbase downloads against a local imitation of its flow. The tests check that the countdown is waited out, that the form fields are submitted, cancelling mid-countdown, direct file answers, and the hand-off to the browser on error pages, missing forms or missing links.
- The queue, including required mods, against a fake catalogue whose page loads and lookups can be held back or fail. Also app state and UI behaviour: search, double-click to queue, Owner ID buttons, settings validation.

## Build

`build.bat` creates (or reuses) `.venv`, installs `requirements.txt` into it, and runs PyInstaller from there with `WRSR Mod Installer.spec`. The result is a single windowed `dist/WRSR Mod Installer.exe` that bundles the `logos` folder. `run.bat` uses the same `.venv`.

Earlier builds drove modsbase through a hidden browser (Playwright). That was dropped: Cloudflare in front of modsbase now answers headless browsers with a bot check (403, `cf-mitigated: challenge`) that never clears, while plain requests get the normal page.

PyInstaller only *warns* about modules it can't find. Building with a Python that lacks the requirements therefore produced a 9 MB exe that failed with "No module named 'PyQt5'", so the spec now stops the build in that case. `.gitattributes` pins `*.bat` files to CRLF line endings.

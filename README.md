# WRSR Mod Installer

A desktop app to manage, fix and download mods for **Workers & Resources: Soviet Republic**: find mods on the Skymods catalogue, download them together with the mods they need, and set the Owner ID in each mod's `workshopconfig.ini`.

## Features

### Library
- 🔍 Lists every mod in `media_soviet\workshop_wip`, with its name, type, folder and Owner ID
- 🎯 Shows at a glance which mods already carry your Owner ID (**Fixed**) and which still need it
- ⚙️ Applies your Owner ID to one mod, or to all of them with one click
- 🖼️ Shows the selected mod's preview image and description beside the list, with no pop-ups
- 📦 Installs mods from a ZIP file you already downloaded, with a preview first. An existing copy is only replaced after you confirm, and only once the new copy is safely in place
- 🌍 Reads configs saved in any common encoding (UTF-8, with or without BOM, and Windows-1251) and keeps everything except the Owner ID line byte-for-byte

### Browse Skymods
- 📡 Searches the Skymods catalogue for WRSR mods. The first page appears first, and **Load more** fetches the next
- ⚡ Remembers what Skymods sent: a search or mod you looked at before shows up instantly, then refreshes quietly in the background
- 🏷️ Marks results that are **Installed**, already **In downloads**, or **Need other mods**
- 📋 Shows the description and required mods of the selected result
- ⏹️ The window never freezes while searching; you can stop or replace a slow search at any time

### Downloads
- 📥 Downloads mods one at a time with live progress, and keeps going when one fails
- 🔗 Queues the mods a mod needs as soon as their names are known: straight away if you opened the mod before adding it, otherwise once its page loads. They fill in when they're found on Skymods (by Steam ID, several at once), and the mod's own download never waits for them
- ✋ Cancel, retry or remove any download
- 🌐 Handles modsbase.com's download pages by itself, waiting out their short countdown like any visitor. If a page doesn't behave as usual, it offers **Open download page** so you can finish that download in your browser

### Look and feel
- 🎨 A dark theme in the game's red, with a sidebar, inline notices and small notifications instead of message boxes
- 💾 Remembers your game folder and Owner ID

## Setup

### Prerequisites
- Windows 10 or 11 (the app also runs on macOS and Linux from source)
- Python 3.10 or later to build the executable or run from source; the built exe itself doesn't need Python

### Option 1: Build the executable (recommended)
Double-click `build.bat`. It sets up a private Python environment in `.venv` with everything the app needs, then creates `dist\WRSR Mod Installer.exe`. That's a single file that runs without Python. Close the app first if it's running, since an open exe can't be replaced.

### Option 2: Run from source
Double-click `run.bat`. The first time, it sets up `.venv` the same way.

## How to use

1. **Settings**: choose your game folder (the one that contains `media_soviet`) and enter your Owner ID, normally your 17-digit Steam ID.
2. **Library**: mods marked **Needs Owner ID** get an **Apply** button; **Apply Owner ID to all** fixes them all at once.
3. **Browse**: search for a mod, select a result to read about it, then press **Add to downloads** (or double-click the result). Mods it needs are added automatically.
4. **Downloads**: watch the progress. When the queue is finished, open the Library to apply your Owner ID to the new mods.
5. **Install ZIP…** (Library page) installs a mod archive you downloaded yourself.

Your game folder and Owner ID are saved in `C:\Users\<you>\.wrsr_mod_installer_config.json`. Delete that file to reset them.

Pages from Skymods are kept for up to a week in `%LOCALAPPDATA%\WRSR Mod Installer\cache`. Deleting that folder is always safe.

## How it works

- **Mods** are folders in `media_soviet\workshop_wip` with a `workshopconfig.ini`. The app reads `$ITEM_ID`, `$OWNER_ID`, `$ITEM_TYPE`, `$ITEM_NAME` and `$ITEM_DESC` from it. Applying the Owner ID rewrites only the `$OWNER_ID` line, or adds one at the top.
- **Search** reads catalogue.smods.ru result pages (app 784150). Each result already includes the mod's Steam ID, download link, size and author.
- **Required mods** come from the "Required items" list on a mod's page. That page is only opened when the search listing marks the mod as needing other mods, or was already opened in Browse. Each required mod gets its queue row right away, then is looked up on Skymods by Steam ID, never by name, so a similarly named mod is never downloaded by mistake. Several are looked up at once. Ones you already have are noted on the mod's row instead of queued; ones Skymods doesn't have show as failed rows.
- **Saved pages**: every Skymods page the app fetches is kept on disk for up to a week. Searches younger than 10 minutes, and mod pages and Steam ID lookups younger than a day, are reused without asking Skymods. Older ones are shown at once while a fresh copy loads.
- **Downloads** from modsbase.com work the way a visitor's do. The app opens the page, waits out its countdown, and submits the same download form the Download button submits. It then saves the file that comes back, with live progress. Archives are unpacked to a temporary folder. The mod is found wherever its `workshopconfig.ini` is inside the archive, and the folder is named after `$ITEM_ID`, like the game does.

## Troubleshooting

**The exe says "No module named 'PyQt5'" (or `requests`)**
The exe was built with a Python that didn't have the app's requirements installed. Older versions of `build.bat` used whichever Python came first on PATH. Run the current `build.bat` again: it builds inside `.venv`, and the build now stops with a clear message instead of producing a broken exe.

**Searches or mod details take a long time**
Skymods' server is sometimes fast and sometimes takes up to a minute per page. The app works around it:
- Searches and mods you've seen before show up instantly from the saved copy, then refresh in the background.
- Adding a mod starts its download straight away. Only the mods it needs are looked up, all at once.

Only a brand-new search, or a mod you've never opened, can still take a while. The app shows how long it has been waiting, and you can stop or start another search at any time.

**"Skymods is putting the app through a browser check"**
Skymods' Cloudflare protection sometimes refuses apps for a while and shows a "Just a moment…" check that only a real browser can pass. The app won't try to get around it. Searches and mods you've seen before keep working from saved pages. Otherwise, try again later, or find the mod on catalogue.smods.ru in your browser and use **Install ZIP…**.

**A download offers "Open download page"**
modsbase's page didn't behave as usual: an error, or no Download button or file link. Press **Open download page**, download the file in your browser, then use **Install ZIP…** in the Library.

**"Access denied" when applying the Owner ID**
Close the game and check the mod's files aren't read-only.

**"There's no media_soviet\workshop_wip folder…"**
Choose the folder where the game itself is installed, usually `…\steamapps\common\SovietRepublic`.

## Development

```cmd
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```
(`run.bat` or `build.bat` create `.venv` the first time.)

- `mod_installer.py`: starts the app
- `wrsr_installer/`: the app
  - `workshop.py`: reads and edits `workshopconfig.ini`, scans the workshop folder
  - `archive.py`: unpacks archives and installs mod folders safely
  - `skymods.py`: Skymods search and mod pages
  - `downloader.py`: direct and browser-based downloads, with progress and cancelling
  - `download_queue.py`, `services.py`: the download queue, including required mods
  - `cache.py`: Skymods pages saved on disk
  - `app_state.py`, `config.py`, `tasks.py`: shared state, settings, background work
  - `ui/`: the Qt interface (theme, pages, widgets)
- `tests/`: automated tests; `tests/fixtures/` hold sample Skymods pages
- `logos/`: app icon and artwork

## License

Free to use and modify.

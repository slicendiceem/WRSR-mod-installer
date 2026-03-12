# WRSR Mod Installer

A comprehensive GUI tool to manage, fix, and download mods for Workers and Resources Soviet Republic. Features advanced mod discovery, prerequisite handling, and batch downloading.

## Features

### Mod Management
- 📁 Browse and select your WRSR game folder
- 🔍 Automatically detects all installed mods from `media_soviet\workshop_wip`
- 📝 Displays folder name and actual item name from config
- 🏷️ Automatically categorizes mods by type (Building, Road, Decoration, Vehicle, etc.)
- 🖼️ View detailed mod information with preview images and descriptions
- 🎯 Set a target Owner ID to compare against
- 📊 Shows mod status: Fixed or Not Fixed
- ⚙️ Fix individual mods or all mods at once with one click
- 💾 Remembers your game folder and Owner ID - auto-checks status on startup

### Mod Discovery & Download
- 📡 **Search and download mods from Skymods** with automatic pagination
- 🔗 **Multi-select support** - Select multiple mods and queue them for download
- 🎯 **Queue system** - Download multiple mods sequentially with progress tracking
- 🔄 **Automatic prerequisite detection** - Automatically finds and adds required mods to download queue
- 📋 **Details preview panel** - View mod information without popups blocking the interface
- ⏳ **Three-stage progress tracking**:
  - Queue Progress: Shows position in download queue (X/Total)
  - Link Preparation: Tracks browser operations and link generation
  - File Download: Shows actual file transfer progress (0-100%)
- 🌐 **Browser automation** - Handles modsbase downloads with automatic session management
- 🏗️ Automatic prerequisite installation before main mod

### Interface & UX
- 🎨 Professional UI with WRSR branding
- 📍 Responsive layout with resizable panels
- 🎭 Color-coded mod status indicators
- ✨ Smooth animations and progress feedback

## Setup

### Prerequisites
- Python 3.7 or later
- Windows, macOS, or Linux

### Installation

1. **Install Python dependencies:**
   ```cmd
   pip install -r requirements.txt
   ```

## Usage

### Option 1: Run as an executable (Windows) - Recommended
1. **Build the executable** (one-time setup):
   ```cmd
   build.bat
   ```
   This will create a standalone `WRSR Mod Installer.exe` in the `dist` folder.

2. **Run the executable**:
   Simply double-click `WRSR Mod Installer.exe` (no Python installation needed!)

### Option 2: Run using the batch file (Windows)
Simply double-click `run.bat` (requires Python to be installed)

### Option 3: Run from command prompt
```cmd
python mod_installer.py
```
(requires Python to be installed)

### How to Use

1. **Select Game Folder** - Click "📁 Select Game Folder" and navigate to your WRSR game installation directory

2. **Set Target Owner ID** - Enter the Owner ID you want all mods to use, then click "💾 Save Owner ID"

3. **View Installed Mods** - The app automatically scans and displays all mods organized by type:
   - **Folder Name** - The actual folder name in the workshop_wip directory
   - **Item Name** - The display name from config
   - **Type Column** - Shows the mod category
   - ✓ **Fixed** (Green) - Matches your target ID
   - ✗ **Not Fixed** (Orange) - Has a different ID or no ID set
   - **Click any row** to view detailed mod information

4. **Fix Mods** - Choose:
   - Click the individual "Fix" button on any mod that needs updating
   - Or click "⚡ Fix All" to update all unfixed mods at once

5. **Download Mods From Catalogue**:
   - Click "📡 Download From Catalogue" to open the mod browser
   - **Search** - Type mod name or keywords to search Skymods
   - **Preview** - Click any mod in the results list to see details in the preview panel
   - **Multi-Select** - Select multiple mods from search results
   - **Queue** - Click the arrow button to add selected mods to your download queue
   - **Prerequisites** - The app automatically detects required mods and adds them to the queue
   - **Download All** - Click "Download All in Queue" to start batch downloading
   - **Progress Monitoring**:
     - Queue Progress bar shows which mod you're downloading (e.g., 2/5)
     - Link Preparation bar shows browser/link generation progress
     - File Download bar shows actual file transfer progress (0-100%)
   - Mods are automatically extracted and installed to your workshop_wip folder
   - Already-installed mods are automatically detected and shown in green

6. **Install From ZIP File**:
   - Click "📂 Install From ZIP File" to manually import a mod ZIP archive
   - Select your mod ZIP file and it will be automatically extracted and installed

7. **Refresh** - Click "🔄 Refresh Mods" to re-scan the workshop folder anytime

## Configuration

Your game folder path and Target Owner ID are automatically saved to:
- Windows: `C:\Users\[YourUsername]\.wrsr_mod_installer_config.json`

You can manually delete this file to reset all settings.

## Files

- `mod_installer.py` - Main application
- `requirements.txt` - Python dependencies
- `run.bat` - Quick launch script (Windows, requires Python)
- `build.bat` - Build script to create standalone executable (Windows)
- `logos/` - Application branding assets
  - `wrsrlogo.jfif` - Window icon and taskbar icon
  - `wrsrbanner.png` - Mod selector sidebar banner (200px height)

## How It Works

### Mod Management
1. Scans the `media_soviet\workshop_wip` directory for mod folders
2. Reads the `workshopconfig.ini` file in each mod
3. Extracts: mod name, description, type, owner ID, and preview image
4. Compares each mod's ID against your target Owner ID
5. Displays status: "Fixed" (matches target) or "Not Fixed" (doesn't match)
6. Updates the `$OWNER_ID` value when you click "Fix" or "Fix All"

### Mod Discovery & Download
1. **Search** - Connects to Skymods catalogue and searches for mods by keyword
2. **Pagination** - Automatically fetches all pages of search results
3. **Details** - Fetches mod details in background (image, description, prerequisites)
4. **Selection** - Allows multi-select of mods from search results
5. **Queue** - Builds a download queue with selected mods
6. **Prerequisites** - Extracts required mods from HTML, searches for them, and adds to queue automatically
7. **Download** - Downloads and extracts mods sequentially with real-time progress updates
8. **Installation** - Extracts ZIP to `workshop_wip` folder and applies target Owner ID
9. **Detection** - Recognizes already-installed mods using name normalization

### Progress Tracking
- **Queue Progress** - Shows current position (e.g., 2/5) as mods download
- **Link Preparation** - Shows browser operations (page load, button click, link generation)
- **File Download** - Shows actual file transfer progress from 0-100%

## Troubleshooting

**"Workshop path not found"**
- Make sure you selected the correct game folder (where `media_soviet` folder exists)

**"Python is not recognized"**
- Make sure Python is installed and added to your PATH
- Alternatively, use the full path: `C:\Python\python.exe mod_installer.py`

**Permission denied when updating a mod**
- Close the game if it's running
- Make sure the file isn't write-protected

**Download fails or times out**
- Check your internet connection
- Some mods may take longer to download
- The timeout is set to 30 seconds - longer than typical

**Prerequisites not being added automatically**
- Make sure you have internet connection
- The app searches by Steam ID
- If a prerequisite mod isn't found on Skymods, it won't be added

**"ModsBase redirect" errors during download**
- Some download mirrors require browser session handling
- The app uses Playwright to handle this automatically
- If issues persist, try downloading a simpler mod first to test connectivity

**sipPyTypeDict deprecation warnings**
- These are harmless PyQt5 internal warnings
- They don't affect functionality and can be safely ignored
- Caused by library compatibility, not your code

## License

Free to use and modify.

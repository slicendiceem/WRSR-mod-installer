# WRSR Mod Installer

A simple GUI tool to manage and fix mod Owner IDs in Workers and Resources Soviet Republic workshop mods.

## Features

- 📁 Browse and select your WRSR game folder
- 🔍 Automatically detects all installed mods from `media_soviet\workshop_wip`
- 📝 Displays both folder name and actual item name from config
- 🏷️ Automatically categorizes mods by type (Building, Road, Decoration, etc.)
- 🖼️ Click any mod to view preview image and full description
- 🎯 Set a target Owner ID to compare against
- 📊 Shows mod status: Fixed or Not Fixed
- ⚙️ Easily fix individual mods or fix all at once with one click
- 💾 Remembers your game folder and Owner ID - auto-checks status on startup
- ⚡ "Fix All" button to batch update all unfixed mods
- 📡 **Search and download mods from Skymods** with automatic pagination (fetches ALL results)

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

3. **View Mods** - The app automatically scans and displays all mods organized by type:
   - **Folder Name** - The actual folder name in the workshop_wip directory
   - **Item Name** - The display name from config (e.g., "Old Town Pack")
   - **Type Column** - Shows the mod category (Building, Road, Decoration, Vehicle, etc.)
   - ✓ **Fixed** (Green) - Matches your target ID
   - ✗ **Not Fixed** (Orange) - Has a different ID or no ID set
   - Mods are automatically grouped by type for easy organization
   - **Click any row** to view detailed mod information including preview image and description

4. **Auto-Check on Startup** - Next time you open the app, if you have a game folder and Owner ID saved, it automatically checks the status of all mods

5. **Fix Mods** - Choose:
   - Click the individual "Fix" button on any mod that needs updating
   - Or click "⚡ Fix All" to update all unfixed mods at once

6. **Download From Skymods** - Click "📡 Download From Catalogue" to:
   - Search for mods by name (e.g., "road", "building", specific mod names)
   - The app automatically fetches ALL search results (multiple pages)
   - View detailed information about each mod found
   - Download and extract 7z archives automatically to your workshop_wip folder
   - Preview the mod before applying the fix
   - Confirm to automatically apply your target Owner ID
   - The mod appears in your list immediately, ready to use!

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

## How It Works

The tool:
1. Scans the `media_soviet\workshop_wip` directory for mod folders
2. Reads the `workshopconfig.ini` file in each mod
3. Extracts the mod name from `$ITEM_NAME` value
4. Extracts the mod description from `$ITEM_DESC` value (supports multiline)
5. Extracts the mod type from `$ITEM_TYPE WORKSHOP_ITEMTYPE_*` value
6. Looks for `previewimage.png` in each mod folder
7. Extracts the current `$OWNER_ID` value
8. Organizes mods by type for easy viewing
9. Compares each mod's ID against your target Owner ID
10. Displays as either "Fixed" (matches target) or "Not Fixed" (doesn't match)
11. Allows viewing mod details (image, name, description) by clicking on any row
12. Can update the `$OWNER_ID` value when you click "Fix" or "Fix All"
13. Automatically checks status on startup if you have settings saved

## Troubleshooting

**"Workshop path not found"**
- Make sure you selected the correct game folder (where `media_soviet` folder exists)

**"Python is not recognized"**
- Make sure Python is installed and added to your PATH
- Alternatively, use the full path: `C:\Python\python.exe mod_installer.py`

**Permission denied when updating a mod**
- Close the game if it's running
- Make sure the file isn't write-protected

## License

Free to use and modify.

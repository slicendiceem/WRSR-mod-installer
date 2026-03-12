# WRSR Mod Installer - Codebase Analysis

## 1. Project Overview

**Purpose**: A GUI tool for managing and fixing mod Owner IDs in "Workers and Resources: Soviet Republic" (WRSR) workshop mods.

**Core Functionality**:
- Scan and display installed mods from `media_soviet/workshop_wip`
- Compare mod Owner IDs against a target ID
- Fix individual or all mods by updating their `$OWNER_ID` in `workshopconfig.ini`
- Search, download, and install mods from Skymods catalogue
- Preview mod details (images, descriptions)
- Batch operations for efficiency

**Technology Stack**:
- Python 3.7+
- PyQt5 for GUI
- Requests for HTTP operations
- PyInstaller for executable packaging
- Windows-focused but cross-platform capable

## 2. Architecture & Design Patterns

### 2.1 MVC-like Architecture
- **Model**: `ModScanner`, `ModDownloader`, `ModSearchThread` handle data operations
- **View**: PyQt5 widgets (`QMainWindow`, `QDialog`, `QTableWidget`)
- **Controller**: `ModInstallerApp` coordinates between models and views

### 2.2 Multithreading Design
- Heavy operations run in background threads (`QThread`) to keep UI responsive:
  - `ModScanner`: Scans filesystem for mods
  - `ModDownloader`: Downloads and extracts mod archives
  - `ModSearchThread`: Searches Skymods catalogue
- Thread communication via PyQt signals (`pyqtSignal`)

### 2.3 Modular Class Structure

#### Core Classes:
1. **`ModInstallerApp`** (`QMainWindow`)
   - Main application window
   - Manages UI components and user interactions
   - Coordinates between different components
   - Handles configuration persistence

2. **`ModScanner`** (`QThread`)
   - Scans `workshop_wip` directory for mods
   - Parses `workshopconfig.ini` files
   - Extracts metadata: name, description, type, Owner ID
   - Emits list of mods when complete

3. **`ModDownloader`** (`QThread`)
   - Downloads mod archives from URLs
   - Extracts ZIP files
   - Moves mods to `workshop_wip` directory
   - Reads mod configuration after extraction

4. **`ModSearchThread`** (`QThread`)
   - Searches Skymods catalogue via web scraping
   - Parses HTML results with regex patterns
   - Paginates through search results
   - Extracts download links and mod details

5. **`ModCatalogueDialog`** (`QDialog`)
   - UI for searching and browsing Skymods
   - Displays search results with details
   - Handles prerequisite checking
   - Initiates downloads

6. **`ModDetailsDialog`** (`QDialog`)
   - Displays detailed mod information
   - Shows preview images
   - Renders formatted descriptions with wiki markup

7. **`ModDetailsDialog`** (`QDialog`)
   - Preview dialog for mod details

### 2.4 Configuration Management
- JSON configuration file at `~/.wrsr_mod_installer_config.json`
- Stores `game_folder` and `target_owner_id`
- Auto-loads on startup, auto-saves on changes

## 3. Key Data Structures

### Mod Dictionary Format:
```python
{
    'name': 'folder_name',           # Directory name
    'path': '/full/path/to/mod',     # Absolute path
    'config_path': '/path/workshopconfig.ini',
    'owner_id': '12345',             # Current Owner ID (or None)
    'item_type': 'Building',         # Mod category
    'item_name': 'Display Name',     # Human-readable name
    'item_desc': 'Description text'  # May contain wiki markup
}
```

### Configuration Format:
```json
{
    "game_folder": "C:/Games/WRSR",
    "target_owner_id": "12345"
}
```

## 4. File Processing Logic

### 4.1 Mod Detection
1. Scan `media_soviet/workshop_wip/*` directories
2. Look for `workshopconfig.ini` in each
3. Parse with regex patterns:
   - `\$OWNER_ID\s*[=\s]\s*(\d+)`
   - `\$ITEM_TYPE\s*WORKSHOP_ITEMTYPE_(\w+)`
   - `\$ITEM_NAME\s+"([^"]+)"`
   - `\$ITEM_DESC\s+"([\s\S]*?)"\s*(?=\$|\Z)`

### 4.2 Owner ID Fixing
1. Read `workshopconfig.ini` content
2. Replace existing `$OWNER_ID` line with new value
3. If no `$OWNER_ID` exists, prepend it to file
4. Write back with UTF-8 encoding

### 4.3 Archive Handling
- Supports ZIP archives only
- Extracts to temporary directory
- Identifies mod folder (first directory in archive)
- Renames folder to Steam mod ID if available
- Moves to `workshop_wip` directory

## 5. Web Integration

### 5.1 Skymods Catalogue
- Base URL: `https://catalogue.smods.ru`
- Search: `/?s={term}&app=784150` (WRSR app ID)
- Pagination: `/page/{page}?s={term}&app=784150`
- HTML scraping with regex patterns

### 5.2 Download Link Extraction
- Multiple regex patterns attempt to find ZIP download links
- Special handling for `modsbase.com` URLs
- Fallback to manual download if automatic fails

### 5.3 Prerequisite Checking
- Parses mod descriptions for "Requires"/"Depends" mentions
- Compares against installed mods (normalized name matching)
- Warns user about missing dependencies

## 6. User Interface Components

### 6.1 Main Window Layout
```
┌─────────────────────────────────────────────────────────────┐
│ WRSR Mod Installer                    [Select Game Folder]  │
├──────────────┬──────────────────────────────────────────────┤
│ Left Panel   │ Right Panel (Mods Table)                     │
│ - Game folder│ - Mod list with columns:                     │
│ - Owner ID   │   Folder, Name, Type, ID, Status, Action     │
│ - Buttons:   │ - Statistics: Fixed/Not Fixed counts         │
│   • Refresh  │ - Click row for details                      │
│   • Download │                                              │
│   • Fix All  │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

### 6.2 Dialog Windows
- **Mod Details**: Shows preview image, description, metadata
- **Catalogue Browser**: Search interface for Skymods
- **Progress Dialogs**: For downloads and operations

### 6.3 Table Features
- Color-coded status (green/orange)
- Grouped by mod type
- Clickable rows for details
- Action buttons per row for fixing

## 7. Build & Deployment

### 7.1 Dependencies
```txt
PyQt5==5.15.9      # GUI framework
PyInstaller==6.1.0  # Executable packaging
requests==2.31.0    # HTTP client
```

### 7.2 Build Process (`build.bat`)
1. Checks for PyInstaller installation
2. Installs if missing
3. Runs: `pyinstaller --onefile --windowed --name "WRSR Mod Installer" mod_installer.py`
4. Output: Single executable in `dist/` folder

### 7.3 Execution Options
1. **Executable**: `dist/WRSR Mod Installer.exe` (standalone)
2. **Batch file**: `run.bat` (requires Python)
3. **Direct**: `python mod_installer.py`

## 8. Error Handling & Robustness

### 8.1 Common Issues Handled
- Missing game folder
- Invalid Owner ID format
- Permission errors when writing files
- Network failures during downloads
- Corrupted or invalid ZIP archives
- Missing `workshopconfig.ini` files

### 8.2 Recovery Mechanisms
- Temporary file cleanup
- Thread cancellation on errors
- User-friendly error messages
- Configuration fallbacks

### 8.3 Debug Features
- Extensive `[DEBUG]` logging
- HTML page saving for troubleshooting
- Progress reporting for long operations

## 9. Potential Issues & Limitations

### 9.1 Technical Limitations
1. **Web Scraping Fragility**: Relies on Skymods HTML structure; changes break search
2. **ZIP-only Archives**: Doesn't support RAR, 7z, or other formats
3. **Windows Path Assumptions**: Uses backslashes but `pathlib` helps cross-platform
4. **Encoding Assumptions**: Assumes UTF-8 for config files
5. **No Mod Updates**: Cannot update existing mods to newer versions
6. **No Conflict Detection**: Doesn't check for mod conflicts or load order

### 9.2 Security Considerations
- Downloads and executes arbitrary ZIP files
- No signature verification for mods
- Web scraping may violate Skymods terms of service
- Stores configuration in user home directory

### 9.3 Usability Issues
- No batch rename functionality
- Cannot reorder mods
- No backup before modifying files
- Limited search filtering options

## 10. Extension Points & Improvement Opportunities

### 10.1 Immediate Improvements
1. **Add 7z Support**: Use `py7zr` for additional archive formats
2. **Better Error Recovery**: Retry mechanisms for downloads
3. **Mod Backup**: Create backups before modifying files
4. **Batch Rename**: Rename multiple mod folders at once
5. **Load Order Management**: Drag-and-drop reordering

### 10.2 Advanced Features
1. **Mod Version Checking**: Compare against Steam Workshop versions
2. **Dependency Resolution**: Automatically download prerequisites
3. **Mod Packs**: Create and install collections of mods
4. **Cloud Sync**: Sync configuration across devices
5. **Steam Workshop Integration**: Direct API access

### 10.3 Code Quality Improvements
1. **Replace Regex Parsing**: Use proper HTML parser (BeautifulSoup)
2. **Add Unit Tests**: Test mod scanning and fixing logic
3. **Configuration Validation**: Validate game folder structure
4. **Internationalization**: Support multiple languages
5. **Plugin Architecture**: Allow community extensions

## 11. Usage Scenarios

### 11.1 Basic User Flow
1. User selects game folder
2. Sets target Owner ID
3. App scans and displays mods
4. User reviews which mods need fixing
5. Clicks "Fix All" or individual "Fix" buttons
6. Mods are updated with correct Owner ID

### 11.2 Mod Download Flow
1. User clicks "Download From Catalogue"
2. Searches for mods by name
3. Selects mod from results
4. App downloads and extracts mod
5. Shows preview and asks for confirmation
6. Applies Owner ID fix automatically
7. Mod appears in main list

### 11.3 Manual Installation Flow
1. User clicks "Install From ZIP File"
2. Selects local ZIP archive
3. App extracts and shows preview
4. User confirms installation
5. App applies Owner ID fix if confirmed

## 12. Code Quality Assessment

### 12.1 Strengths
- Clear separation of concerns
- Responsive UI with threading
- Comprehensive error handling
- Good user feedback mechanisms
- Modular design allows easy extension
- Extensive logging for debugging

### 12.2 Weaknesses
- Heavy reliance on regex for HTML parsing
- Limited test coverage (no tests found)
- Some duplicated code (URL extraction logic)
- Mixed concerns in some classes
- Hardcoded strings and magic numbers

### 12.3 Maintainability
- **High**: Well-structured with clear responsibilities
- **Moderate**: Some complex methods could be refactored
- **Good**: Consistent coding style and documentation

## 13. Dependencies & Compatibility

### 13.1 Python Dependencies
- **PyQt5**: GUI framework (LGPL licensed)
- **requests**: HTTP client (Apache 2.0)
- **PyInstaller**: Packaging (GPL)

### 13.2 System Requirements
- **OS**: Windows (primary), macOS/Linux (theoretically)
- **Python**: 3.7+
- **Disk Space**: ~50MB for executable
- **Network**: Required for catalogue features

### 13.3 Game Compatibility
- **WRSR Version**: All versions using `workshopconfig.ini` format
- **Mod Format**: Standard WRSR workshop mod structure
- **Paths**: Expects `media_soviet/workshop_wip` directory

## 14. Conclusion

The WRSR Mod Installer is a well-designed, functional tool that solves a specific problem for WRSR modders. Its architecture demonstrates good software engineering practices with proper threading, modular design, and user-friendly interfaces. While there are areas for improvement (particularly around web scraping fragility and archive format support), the codebase is maintainable and extensible.

The tool successfully bridges the gap between manual mod management and automated solutions, providing value to the WRSR modding community. Its open-ended design allows for future enhancements while remaining focused on its core mission: simplifying Owner ID management for workshop mods.

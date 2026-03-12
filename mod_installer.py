import sys
import os
import json
import re
import tempfile
import zipfile
from pathlib import Path
import requests
from html.parser import HTMLParser
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QMessageBox, QHeaderView, QSplitter, QFrame, QSpinBox, QDialog, QScrollArea,
    QListWidget, QListWidgetItem, QComboBox, QProgressBar, QAbstractItemView
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QIcon, QColor, QFont, QBrush, QPixmap

# Configuration file location
CONFIG_FILE = Path.home() / '.wrsr_mod_installer_config.json'


class ModDownloader(QThread):
    """Background thread for downloading and extracting mods"""
    progress = pyqtSignal(str, int)  # mod_name, percent complete
    finished = pyqtSignal(dict)       # mod_data dict with extracted info
    error = pyqtSignal(str)

    def __init__(self, download_url, mod_name, game_folder, target_owner_id, mod_id=None):
        super().__init__()
        self.download_url = download_url
        self.mod_name = mod_name
        self.game_folder = game_folder
        self.target_owner_id = target_owner_id
        self.mod_id = mod_id  # Steam mod ID to rename folder to
        self.temp_dir = None

    def run(self):
        try:
            # Create temporary directory for download
            self.temp_dir = tempfile.mkdtemp()

            # Download the file
            zip_path = Path(self.temp_dir) / f'{self.mod_name}.zip'
            self._download_file(self.download_url, zip_path)

            # Extract to temp folder first
            extract_temp = Path(self.temp_dir) / 'extracted'
            self._extract_mod(zip_path, extract_temp)

            # Find the mod folder inside the extracted contents and rename it
            workshop_wip = Path(self.game_folder) / 'media_soviet' / 'workshop_wip'
            workshop_wip.mkdir(parents=True, exist_ok=True)

            # Find the mod folder (should be a single directory at root of extraction)
            extracted_contents = list(extract_temp.iterdir())
            if not extracted_contents:
                raise Exception("Extracted archive is empty")

            # Find the first directory (the mod folder)
            mod_folder = None
            for item in extracted_contents:
                if item.is_dir():
                    mod_folder = item
                    break

            if not mod_folder:
                raise Exception("No mod folder found in archive")

            # Determine final folder name - use mod_id if available, otherwise use original name
            final_folder_name = self.mod_id if self.mod_id else mod_folder.name
            final_path = workshop_wip / final_folder_name

            # Move mod folder to workshop_wip with new name
            if final_path.exists():
                import shutil
                shutil.rmtree(final_path)
            mod_folder.rename(final_path)

            # Read extracted mod config to get metadata
            mod_data = self._read_mod_config(final_path)
            mod_data['path'] = str(final_path)

            self.finished.emit(mod_data)

        except Exception as e:
            self.error.emit(f"Failed to process mod: {str(e)}")
        finally:
            # Clean up temp directory
            if self.temp_dir and Path(self.temp_dir).exists():
                import shutil
                try:
                    shutil.rmtree(self.temp_dir)
                except:
                    pass

    def _download_file(self, url, dest_path):
        """Download file with progress updates, handling modsbase redirects"""
        try:
            print(f"[DEBUG] Starting download from: {url}")

            # Special handling for modsbase URLs
            if 'modsbase.com' in url:
                print(f"[DEBUG] Detected modsbase URL - checking if direct download is available...")
                # Try simple fallback first
                if url.endswith('.html'):
                    simple_url = url[:-5]
                    print(f"[DEBUG] Trying direct URL without .html: {simple_url}")
                    response = requests.head(simple_url, timeout=10)
                    if response.status_code == 200:
                        content_type = response.headers.get('content-type', '').lower()
                        if 'application/zip' in content_type or 'application/octet-stream' in content_type:
                            print(f"[DEBUG] Direct URL works as ZIP file!")
                            url = simple_url
                        else:
                            print(f"[DEBUG] Direct URL returned: {content_type}")

            print(f"[DEBUG] Final download URL: {url}")
            response = requests.get(url, stream=True, timeout=30, allow_redirects=True)
            response.raise_for_status()

            print(f"[DEBUG] HTTP Status: {response.status_code}")
            print(f"[DEBUG] Content-Type: {response.headers.get('content-type', 'unknown')}")
            print(f"[DEBUG] Content-Length: {response.headers.get('content-length', 'unknown')}")

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            self.progress.emit(self.mod_name, percent)

            file_size = dest_path.stat().st_size
            print(f"[DEBUG] Download complete. File size: {file_size} bytes")

            # Check if we downloaded HTML by mistake
            if file_size < 100000:  # Mods should be bigger than 100KB typically
                first_bytes = dest_path.read_bytes()[:50]
                if b'<!DOCTYPE' in first_bytes or b'<html' in first_bytes:
                    print(f"[DEBUG] ERROR: Downloaded file appears to be HTML, not a ZIP")
                    raise Exception("Modsbase requires manual interaction (clicking button). Please download the file manually and use 'Install From ZIP File' button instead.")

        except requests.exceptions.RequestException as e:
            if 'modsbase.com' in str(url):
                raise Exception(f"Download failed: {str(e)}\n\nNote: modsbase.com requires clicking a button to generate download links. Please download manually and use 'Install From ZIP File' button.")
            else:
                raise Exception(f"Download failed: {str(e)}")

    def _extract_direct_modsbase_link(self, modsbase_url):
        """Extract the direct ZIP download link from modsbase.com page"""
        try:
            print(f"[DEBUG] Fetching modsbase page: {modsbase_url}")
            response = requests.get(modsbase_url, timeout=10)
            response.raise_for_status()

            print(f"[DEBUG] Modsbase page fetched. Content length: {len(response.text)} chars")
            print(f"[DEBUG] Page URL after redirects: {response.url}")

            import re

            # Save the HTML page for inspection
            debug_file = Path.home() / 'modsbase_debug.html'
            try:
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                print(f"[DEBUG] Saved modsbase HTML page to: {debug_file}")
            except:
                pass

            # Look for actual download links (not the .html page itself)
            patterns = [
                # Match .zip files that are NOT followed by .html
                r'href=["\']([^"\']*\.zip)(?!\.html)["\']',
                # Look for links with /download/ in them
                r'href=["\']([^"\']*?/download[^"\']*?\.zip[^"\']*?)["\']',
                # Look for data-file or file attributes
                r'data-file=["\']([^"\']*\.zip[^"\']*)["\']',
                r'file=["\']([^"\']*\.zip[^"\']*)["\']',
                # Look for any URL with .zip not followed by .html
                r'([^"\'<>\s]*\.zip)(?!\.html)',
            ]

            for i, pattern in enumerate(patterns):
                print(f"[DEBUG] Trying pattern {i+1}: {pattern}")
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                for link in matches:
                    # Skip if it's the HTML page URL or a placeholder
                    if not link or link.endswith('.html') or link.startswith('$') or len(link) < 10:
                        continue

                    print(f"[DEBUG] Pattern {i+1} matched! Found: {link}")

                    if link.startswith('/'):
                        link = 'https://modsbase.com' + link
                    elif not link.startswith('http'):
                        link = modsbase_url.rsplit('/', 1)[0] + '/' + link

                    print(f"[DEBUG] Constructed link: {link}")
                    return link

            print("[DEBUG] No direct download link found in page HTML")
            print(f"[DEBUG] Check the saved HTML at: {debug_file}")

        except Exception as e:
            print(f"[DEBUG] Error in _extract_direct_modsbase_link: {str(e)}")

        print("[DEBUG] Failed to extract link from modsbase page")
        return None

    def _extract_mod(self, archive_path, dest_path):
        """Extract mod archive (ZIP format) to destination"""
        try:
            print(f"[DEBUG] Opening archive: {archive_path}")
            print(f"[DEBUG] Archive file size: {archive_path.stat().st_size} bytes")

            with zipfile.ZipFile(archive_path, 'r') as archive:
                file_list = archive.namelist()

                if not file_list:
                    raise Exception("Archive is empty")

                print(f"[DEBUG] Archive contains {len(file_list)} files")
                print(f"[DEBUG] First 10 files: {file_list[:10]}")

                # Extract all files to destination
                dest_path.mkdir(parents=True, exist_ok=True)
                print(f"[DEBUG] Extracting to: {dest_path}")
                archive.extractall(path=dest_path)
                print(f"[DEBUG] Extraction complete")

        except zipfile.BadZipFile as e:
            print(f"[DEBUG] BadZipFile error: {str(e)}")
            print(f"[DEBUG] Archive path: {archive_path}")
            print(f"[DEBUG] First 100 bytes of file: {archive_path.read_bytes()[:100]}")
            raise Exception("Invalid archive format - expected ZIP file")
        except Exception as e:
            print(f"[DEBUG] Extraction error: {str(e)}")
            raise Exception(f"Extraction failed: {str(e)}")

    def _read_mod_config(self, mod_path):
        """Read mod configuration from extracted workshopconfig.ini"""
        config_path = Path(mod_path) / 'workshopconfig.ini'

        if not config_path.exists():
            raise Exception("workshopconfig.ini not found in extracted mod")

        content = config_path.read_text(encoding='utf-8')

        # Extract metadata (reuse existing regex patterns)
        owner_id_match = re.search(r'\$OWNER_ID\s*[=\s]\s*(\d+)', content)
        owner_id = owner_id_match.group(1).strip() if owner_id_match else None

        item_type_match = re.search(r'\$ITEM_TYPE\s*WORKSHOP_ITEMTYPE_(\w+)', content)
        item_type = item_type_match.group(1) if item_type_match else 'Unknown'

        item_name_match = re.search(r'\$ITEM_NAME\s+"([^"]+)"', content)
        item_name = item_name_match.group(1) if item_name_match else 'Unknown'

        item_desc_match = re.search(r'\$ITEM_DESC\s+"([\s\S]*?)"\s*(?=\$|\Z)', content)
        item_desc = item_desc_match.group(1) if item_desc_match else 'No description'

        return {
            'name': mod_path.name,
            'config_path': str(config_path),
            'owner_id': owner_id,
            'item_type': item_type,
            'item_name': item_name,
            'item_desc': item_desc,
        }


class ModScanner(QThread):
    """Background thread for scanning mods"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, game_folder):
        super().__init__()
        self.game_folder = game_folder

    def run(self):
        try:
            workshop_path = Path(self.game_folder) / 'media_soviet' / 'workshop_wip'

            if not workshop_path.exists():
                self.error.emit(f"Workshop path not found:\n{workshop_path}")
                return

            mods = []
            for mod_dir in workshop_path.iterdir():
                if not mod_dir.is_dir():
                    continue

                config_path = mod_dir / 'workshopconfig.ini'
                if config_path.exists():
                    try:
                        content = config_path.read_text(encoding='utf-8')
                        # Match both formats: $OWNER_ID=12345 and $OWNER_ID 12345
                        owner_id_match = re.search(r'\$OWNER_ID\s*[=\s]\s*(\d+)', content)
                        owner_id = owner_id_match.group(1).strip() if owner_id_match else None

                        # Extract item type
                        item_type_match = re.search(r'\$ITEM_TYPE\s*WORKSHOP_ITEMTYPE_(\w+)', content)
                        item_type = item_type_match.group(1) if item_type_match else 'Unknown'

                        # Extract item name
                        item_name_match = re.search(r'\$ITEM_NAME\s+"([^"]+)"', content)
                        item_name = item_name_match.group(1) if item_name_match else 'Unknown'

                        # Extract item description (multiline)
                        item_desc_match = re.search(r'\$ITEM_DESC\s+"([\s\S]*?)"\s*(?=\$|\Z)', content)
                        item_desc = item_desc_match.group(1) if item_desc_match else 'No description'

                        mods.append({
                            'name': mod_dir.name,
                            'path': str(mod_dir),
                            'config_path': str(config_path),
                            'owner_id': owner_id,
                            'item_type': item_type,
                            'item_name': item_name,
                            'item_desc': item_desc,
                        })
                    except Exception as e:
                        print(f"Error reading {config_path}: {e}")

            mods.sort(key=lambda x: (x['item_type'], x['name']))
            self.finished.emit(mods)

        except Exception as e:
            self.error.emit(f"Error scanning mods: {str(e)}")


class ModDetailsDialog(QDialog):
    """Dialog to display mod details"""
    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(f"Mod Details - {mod['item_name']}")
        self.setGeometry(200, 200, 700, 600)

        layout = QVBoxLayout()

        # Title
        title = QLabel(mod['item_name'])
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Preview image
        image_path = Path(mod['path']) / 'previewimage.png'
        if image_path.exists():
            image_label = QLabel()
            pixmap = QPixmap(str(image_path))
            # Scale image to fit but maintain aspect ratio, with max height
            scaled_pixmap = pixmap.scaledToWidth(300, Qt.SmoothTransformation)
            if scaled_pixmap.height() > 200:
                scaled_pixmap = pixmap.scaledToHeight(200, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_label)
        else:
            no_image = QLabel("No preview image (previewimage.png not found)")
            no_image.setAlignment(Qt.AlignCenter)
            no_image.setStyleSheet("color: gray; font-style: italic;")
            layout.addWidget(no_image)

        # Description
        desc_label = QLabel("Description:")
        desc_label_font = QFont()
        desc_label_font.setBold(True)
        desc_label.setFont(desc_label_font)
        layout.addWidget(desc_label)

        # Scrollable description
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        desc_content = QLabel(self.format_description(mod['item_desc']))
        desc_content.setWordWrap(True)
        desc_content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(desc_content)
        layout.addWidget(scroll)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.setLayout(layout)

    def format_description(self, text):
        """Convert wiki-style markup to HTML"""
        html = text
        # Convert [h1]...[/h1] to HTML headers
        html = re.sub(r'\[h1\](.*?)\[/h1\]', r'<h2>\1</h2>', html, flags=re.DOTALL)
        html = re.sub(r'\[h2\](.*?)\[/h2\]', r'<h3>\1</h3>', html, flags=re.DOTALL)
        html = re.sub(r'\[h3\](.*?)\[/h3\]', r'<h4>\1</h4>', html, flags=re.DOTALL)

        # Convert [b]...[/b] to bold
        html = re.sub(r'\[b\](.*?)\[/b\]', r'<b>\1</b>', html, flags=re.DOTALL)

        # Convert [i]...[/i] to italic
        html = re.sub(r'\[i\](.*?)\[/i\]', r'<i>\1</i>', html, flags=re.DOTALL)

        # Convert [u]...[/u] to underline
        html = re.sub(r'\[u\](.*?)\[/u\]', r'<u>\1</u>', html, flags=re.DOTALL)

        # Convert newlines to <br>
        html = html.replace('\n', '<br>')

        return html


class ModSearchThread(QThread):
    """Background thread for searching mods on Skymods"""
    progress = pyqtSignal(str, int)  # message, results_count
    results_found = pyqtSignal(list)  # mods found on this page (for immediate display)
    finished = pyqtSignal(list)      # results list (final)
    error = pyqtSignal(str)

    SKYMODS_BASE_URL = 'https://catalogue.smods.ru'

    def __init__(self, search_term):
        super().__init__()
        self.search_term = search_term

    def run(self):
        try:
            all_mods = []
            page = 1
            max_pages = 50

            while page <= max_pages:
                try:
                    # First page: /?s={term}&app=784150
                    # Other pages: /page/{page}?s={term}&app=784150
                    if page == 1:
                        url = f'{self.SKYMODS_BASE_URL}/?s={self.search_term}&app=784150'
                    else:
                        url = f'{self.SKYMODS_BASE_URL}/page/{page}?s={self.search_term}&app=784150'
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    mods_on_page = self._parse_results_page(response.text)

                    if not mods_on_page:
                        break

                    all_mods.extend(mods_on_page)
                    # Emit both progress and the new mods found
                    self.progress.emit(f'Fetched page {page}... Found {len(all_mods)} mod(s)', len(all_mods))
                    self.results_found.emit(mods_on_page)  # Add to list immediately
                    page += 1

                except Exception as e:
                    if page == 1:
                        raise
                    break

            self.finished.emit(all_mods)

        except Exception as e:
            self.error.emit(f"Search error: {str(e)}")

    def _parse_results_page(self, html):
        """Parse a single Skymods search results page"""
        mods = []
        try:
            import re

            post_pattern = r'<h[2-3][^>]*class="[^"]*post-title[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a'
            matches = re.finditer(post_pattern, html, re.IGNORECASE | re.DOTALL)

            for match in matches:
                mod_url = match.group(1)
                mod_name = match.group(2).strip()

                if mod_url and mod_name:
                    # Extract Steam mod ID from URL (e.g., https://catalogue.smods.ru/archives/421998 -> 421998)
                    mod_id_match = re.search(r'/archives/(\d+)', mod_url)
                    mod_id = mod_id_match.group(1) if mod_id_match else None

                    mods.append({
                        'name': mod_name[:100],
                        'url': mod_url,
                        'mod_id': mod_id,
                        'download_url': None,
                    })

            if not mods:
                link_pattern = r'<a[^>]*href="' + re.escape(self.SKYMODS_BASE_URL) + r'/([^/"]+)[^"]*"[^>]*>([^<]{5,100})</a>'
                matches = re.finditer(link_pattern, html)

                for match in matches:
                    mod_slug = match.group(1)
                    mod_name = match.group(2).strip()

                    if self.search_term.lower() in mod_name.lower():
                        mod_url = f'{self.SKYMODS_BASE_URL}/{mod_slug}'
                        # Try to extract ID from slug if it's numeric
                        mod_id = mod_slug if mod_slug.isdigit() else None
                        mods.append({
                            'name': mod_name,
                            'url': mod_url,
                            'mod_id': mod_id,
                            'download_url': None,
                        })

        except Exception as e:
            pass

        return mods


class ModCatalogueDialog(QDialog):
    """Dialog for searching and downloading mods from Skymods"""
    mod_selected = pyqtSignal(dict)  # Emits mod data with download_url

    SKYMODS_BASE_URL = 'https://catalogue.smods.ru'

    def __init__(self, parent=None, game_folder=None):
        super().__init__(parent)
        self.setWindowTitle('Search and Download Mods from Skymods')
        self.setGeometry(100, 100, 1100, 700)
        self.search_results = []
        self.selected_mod = None
        self.search_thread = None
        self.game_folder = game_folder

        layout = QVBoxLayout()

        # Search section
        search_section = QVBoxLayout()
        search_section.addWidget(QLabel('Search for mods on Skymods:'))

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Enter mod name (e.g., "Old Town", "Road")')
        search_layout.addWidget(self.search_input)

        search_btn = QPushButton('🔍 Search')
        search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(search_btn)

        search_section.addLayout(search_layout)
        layout.addLayout(search_section)

        # Results section
        self.results_label = QLabel('Enter search term and click Search')
        layout.addWidget(self.results_label)

        # Main section: Two columns
        main_layout = QHBoxLayout()

        # Left: Results list
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel('Search Results:'))

        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.on_result_selected)
        self.results_list.setSelectionMode(QAbstractItemView.SingleSelection)
        list_layout.addWidget(self.results_list)
        main_layout.addLayout(list_layout, 1)

        # Right: Mod details
        details_layout = QVBoxLayout()
        details_layout.addWidget(QLabel('Details:'))
        self.details_label = QLabel('Select a mod from results')
        self.details_label.setWordWrap(True)
        self.details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.details_label.setOpenExternalLinks(True)
        details_layout.addWidget(self.details_label)
        main_layout.addLayout(details_layout, 1)

        layout.addLayout(main_layout, 1)

        # Bottom: Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        download_btn = QPushButton('📥 Download Selected')
        download_btn.clicked.connect(self.on_download_clicked)
        btn_layout.addWidget(download_btn)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def perform_search(self):
        """Search Skymods for mods matching the search term (in background thread)"""
        search_term = self.search_input.text().strip()
        if not search_term:
            self.results_label.setText('Please enter a search term')
            return

        self.results_label.setText(f'Searching for "{search_term}"...')
        self.results_list.clear()
        self.selected_mod = None
        self.details_label.setText('Searching...')

        # Cancel previous search if running
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.quit()
            self.search_thread.wait()

        # Start new search in background thread
        self.search_thread = ModSearchThread(search_term)
        self.search_thread.progress.connect(self.on_search_progress)
        self.search_thread.results_found.connect(self.on_mods_found)  # Add mods immediately
        self.search_thread.finished.connect(self.on_search_complete)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()

    def on_search_progress(self, message, count):
        """Update progress while searching"""
        self.results_label.setText(f'{message}')

    def on_mods_found(self, mods):
        """Add mods to the list immediately as they're found"""
        for mod in mods:
            self.search_results.append(mod)
            status = "✓ Download available" if mod['download_url'] else "⚠ No download"
            display_name = f"{mod['name']} [{status}]"
            self.results_list.addItem(display_name)

    def on_search_complete(self, results):
        """Handle search completion"""
        # Results already added via on_mods_found, just update label
        if self.search_results:
            self.results_label.setText(f'Found {len(self.search_results)} mod(s) - Search complete')
        else:
            search_term = self.search_input.text().strip()
            self.results_label.setText(f'No mods found for "{search_term}"')
            self.details_label.setText('Try a different search term')

    def on_search_error(self, error_msg):
        """Handle search error"""
        self.results_label.setText('Error searching Skymods')
        self.details_label.setText(f'Error: {error_msg}')


    def _extract_download_link(self, mod_page_url):
        """Extract download link, description, image, and prerequisites from mod page"""
        try:
            response = requests.get(mod_page_url, timeout=20)
            response.raise_for_status()

            import re
            # Look for download links (ZIP files from modsbase)
            patterns = [
                r'href="(https://modsbase\.com/[^"]*\.zip[^"]*)"',
                r'href="([^"]*\.zip[^"]*)"',
                r'href="(https://[^"]*download[^"]*)"',
            ]

            download_url = None
            for pattern in patterns:
                match = re.search(pattern, response.text, re.IGNORECASE)
                if match:
                    download_url = match.group(1)
                    if '://' not in download_url:
                        download_url = self.SKYMODS_BASE_URL + download_url
                    break

            # Extract description (look for entry-content or post-content)
            description = ""
            desc_pattern = r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>'
            desc_match = re.search(desc_pattern, response.text, re.IGNORECASE | re.DOTALL)
            if desc_match:
                description = desc_match.group(1)
                # Strip HTML tags
                description = re.sub(r'<[^>]+>', '', description).strip()[:500]

            # Extract image
            image_url = None
            img_pattern = r'<img[^>]*src="([^"]*)"[^>]*'
            img_matches = re.finditer(img_pattern, response.text)
            for img_match in img_matches:
                img_src = img_match.group(1)
                if any(x in img_src.lower() for x in ['/uploads/', 'image', 'mod', 'preview']):
                    image_url = img_src
                    if '://' not in image_url:
                        image_url = self.SKYMODS_BASE_URL + image_url
                    break

            # Extract prerequisites (look for dependency/requirement mentions)
            prerequisites = []
            prereq_pattern = r'(?:Requires?|Depends?|Prerequisites?):\s*([^<\n]+)'
            prereq_matches = re.finditer(prereq_pattern, response.text, re.IGNORECASE)
            for match in prereq_matches:
                prereq_text = match.group(1).strip()
                prerequisites.append(prereq_text)

            return {
                'download_url': download_url,
                'description': description,
                'image_url': image_url,
                'prerequisites': prerequisites,
            }

        except Exception as e:
            return {
                'download_url': None,
                'description': "",
                'image_url': None,
                'prerequisites': [],
            }

    def _populate_results_list(self):
        """Populate the results list widget"""
        self.results_list.clear()
        for mod in self.search_results:
            status = "✓ Download available" if mod['download_url'] else "⚠ No download"
            display_name = f"{mod['name']} [{status}]"
            item = self.results_list.addItem(display_name)

    def on_result_selected(self, item):
        """Show mod details when selected and fetch download link, description, image, and prerequisites"""
        row = self.results_list.row(item)
        if 0 <= row < len(self.search_results):
            self.selected_mod = self.search_results[row]

            details = (
                f"<b>{self.selected_mod['name']}</b><br><br>"
                f"<a href='{self.selected_mod['url']}'>View on Skymods</a><br><br>"
            )

            # If we haven't fetched the details yet, fetch them now
            if self.selected_mod['download_url'] is None:
                details += "Fetching mod details..."
                self.details_label.setText(details)

                # Fetch all mod details
                mod_details = self._extract_download_link(self.selected_mod['url'])
                self.selected_mod['download_url'] = mod_details['download_url']
                self.selected_mod['description'] = mod_details['description']
                self.selected_mod['image_url'] = mod_details['image_url']
                self.selected_mod['prerequisites'] = mod_details['prerequisites']

            # Build details display
            details = f"<b>{self.selected_mod['name']}</b><br><br>"

            if self.selected_mod.get('description'):
                details += f"<b>Description:</b><br>{self.selected_mod['description']}<br><br>"

            if self.selected_mod.get('prerequisites'):
                details += f"<b>Prerequisites:</b><br>"
                for prereq in self.selected_mod['prerequisites']:
                    details += f"• {prereq}<br>"
                details += "<br>"

            if self.selected_mod['download_url']:
                details += "✓ Download link available<br>Click 'Download Selected' to proceed."
            else:
                details += f"⚠ No download found<br><a href='{self.selected_mod['url']}'>Visit page to download manually</a>"

            self.details_label.setText(details)

    def on_download_clicked(self):
        """Check prerequisites, then emit signal when user clicks download"""
        if not self.selected_mod:
            QMessageBox.warning(self, 'Error', 'Please select a mod from results')
            return

        if not self.selected_mod['download_url']:
            QMessageBox.warning(
                self, 'No Download',
                'This mod does not have a download link.\n\n'
                'Please download it manually from the Skymods page.'
            )
            return

        # Check prerequisites if mod is available on this system
        if self.game_folder:
            missing_prereqs = self._check_prerequisites(self.selected_mod)
            if missing_prereqs:
                reply = QMessageBox.warning(
                    self, 'Missing Prerequisites',
                    f'This mod requires:\n\n' + '\n'.join(missing_prereqs) +
                    '\n\nDo you want to continue anyway?',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        self.mod_selected.emit(self.selected_mod)
        self.close()

    def _check_prerequisites(self, mod):
        """Check if mod prerequisites are installed in workshop_wip"""
        if not self.game_folder or not mod.get('prerequisites'):
            return []

        workshop_path = Path(self.game_folder) / 'media_soviet' / 'workshop_wip'
        if not workshop_path.exists():
            return []

        missing = []
        installed_mods = {d.name for d in workshop_path.iterdir() if d.is_dir()}

        def normalize_name(name):
            """Normalize mod names for comparison (ignore spaces, underscores, hyphens)"""
            return re.sub(r'[\s_\-]+', '', name).lower()

        for prereq in mod.get('prerequisites', []):
            # Check if prerequisite mod name appears in installed mods
            prereq_found = False
            normalized_prereq = normalize_name(prereq)

            for installed in installed_mods:
                normalized_installed = normalize_name(installed)
                # Check for exact match after normalization or substring match
                if normalized_prereq == normalized_installed or \
                   normalized_prereq in normalized_installed or \
                   normalized_installed in normalized_prereq:
                    prereq_found = True
                    break

            if not prereq_found:
                missing.append(f"• {prereq.strip()}")

        return missing


class ModInstallerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WRSR Mod Installer')
        self.setGeometry(100, 100, 1200, 700)

        self.game_folder = None
        self.target_owner_id = None
        self.mods = []
        self.scanner_thread = None
        self.downloader_thread = None

        self.load_config()
        self.init_ui()

        # Auto-scan mods on startup if both folder and Owner ID are set
        if self.game_folder and self.target_owner_id:
            # Use QTimer to ensure UI is fully loaded before scanning
            QTimer.singleShot(500, self.refresh_mods)

    def init_ui(self):
        """Initialize the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Header section
        header_layout = QHBoxLayout()

        title_label = QLabel('WRSR Mod Installer')
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)

        header_layout.addWidget(title_label)
        header_layout.addStretch()

        select_folder_btn = QPushButton('📁 Select Game Folder')
        select_folder_btn.clicked.connect(self.select_game_folder)
        header_layout.addWidget(select_folder_btn)

        main_layout.addLayout(header_layout)

        # Content area with splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left sidebar
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)

        # Game folder display
        left_layout.addWidget(QLabel('Game Folder:'))
        game_folder_label = QLineEdit()
        game_folder_label.setReadOnly(True)
        game_folder_label.setText(self.game_folder or 'Not selected')
        self.game_folder_label = game_folder_label
        left_layout.addWidget(game_folder_label)

        left_layout.addSpacing(20)

        # Owner ID section
        left_layout.addWidget(QLabel('Target Owner ID:'))
        owner_id_input = QLineEdit()
        owner_id_input.setPlaceholderText('Enter Owner ID')
        owner_id_input.setText(str(self.target_owner_id) if self.target_owner_id else '')
        self.owner_id_input = owner_id_input
        left_layout.addWidget(owner_id_input)

        save_owner_id_btn = QPushButton('💾 Save Owner ID')
        save_owner_id_btn.clicked.connect(self.save_owner_id)
        left_layout.addWidget(save_owner_id_btn)

        left_layout.addSpacing(20)

        refresh_btn = QPushButton('🔄 Refresh Mods')
        refresh_btn.clicked.connect(self.refresh_mods)
        left_layout.addWidget(refresh_btn)

        download_btn = QPushButton('📡 Download From Catalogue')
        download_btn.setStyleSheet('background-color: #4a90e2; color: white; font-weight: bold;')
        download_btn.clicked.connect(self.open_catalogue_browser)
        self.download_btn = download_btn
        left_layout.addWidget(download_btn)

        select_zip_btn = QPushButton('📂 Install From ZIP File')
        select_zip_btn.setStyleSheet('background-color: #5a7fa8; color: white;')
        select_zip_btn.clicked.connect(self.select_and_install_zip)
        left_layout.addWidget(select_zip_btn)

        fix_all_btn = QPushButton('⚡ Fix All')
        fix_all_btn.setStyleSheet('background-color: #d78521; color: white; font-weight: bold;')
        fix_all_btn.clicked.connect(self.fix_all_mods)
        self.fix_all_btn = fix_all_btn
        left_layout.addWidget(fix_all_btn)

        left_layout.addStretch()

        # Right panel - mods table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)

        right_layout.addWidget(QLabel('Workshop Mods:'))

        # Summary stats
        stats_layout = QHBoxLayout()
        correct_label = QLabel('✓ Correct: 0')
        correct_label.setStyleSheet('color: #41a31d;')
        self.correct_label = correct_label
        stats_layout.addWidget(correct_label)

        incorrect_label = QLabel('✗ Incorrect: 0')
        incorrect_label.setStyleSheet('color: #d78521;')
        self.incorrect_label = incorrect_label
        stats_layout.addWidget(incorrect_label)

        stats_layout.addStretch()
        right_layout.addLayout(stats_layout)

        # Mods table
        self.mods_table = QTableWidget()
        self.mods_table.setColumnCount(6)
        self.mods_table.setHorizontalHeaderLabels(['Folder Name', 'Item Name', 'Type', 'Current ID', 'Status', 'Action'])
        self.mods_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.mods_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.mods_table.itemClicked.connect(self.on_mod_row_clicked)
        right_layout.addWidget(self.mods_table)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter)

    def select_game_folder(self):
        """Let user select the game folder"""
        folder = QFileDialog.getExistingDirectory(
            self,
            'Select WRSR Game Folder',
            self.game_folder or str(Path.home())
        )

        if folder:
            self.game_folder = folder
            self.game_folder_label.setText(folder)
            self.save_config()
            self.refresh_mods()

    def save_owner_id(self):
        """Save the target owner ID"""
        owner_id = self.owner_id_input.text().strip()

        if not owner_id:
            QMessageBox.warning(self, 'Invalid Input', 'Please enter an Owner ID')
            return

        # Ensure it's a clean string
        self.target_owner_id = str(owner_id).strip()
        self.save_config()
        QMessageBox.information(self, 'Success', f'Owner ID saved: {self.target_owner_id}')

        # Auto-refresh mods if there are any
        if self.mods:
            self.update_table()
        elif self.game_folder:
            self.refresh_mods()

    def refresh_mods(self):
        """Scan and refresh the mods list"""
        if not self.game_folder:
            QMessageBox.warning(self, 'Error', 'Please select a game folder first')
            return

        self.mods_table.setRowCount(0)
        self.mods_table.setEnabled(False)

        # Cancel previous scanner if running
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.quit()
            self.scanner_thread.wait()

        self.scanner_thread = ModScanner(self.game_folder)
        self.scanner_thread.finished.connect(self.on_mods_scanned)
        self.scanner_thread.error.connect(self.on_scan_error)
        self.scanner_thread.start()

    def on_mods_scanned(self, mods):
        """Callback when mods are scanned"""
        self.mods = mods
        self.update_table()
        self.mods_table.setEnabled(True)

    def on_scan_error(self, error):
        """Callback for scan errors"""
        self.mods_table.setEnabled(True)
        QMessageBox.critical(self, 'Scan Error', error)

    def update_table(self):
        """Update the mods table display"""
        self.mods_table.setRowCount(len(self.mods))

        correct_count = 0
        incorrect_count = 0

        for row, mod in enumerate(self.mods):
            # Folder name
            name_item = QTableWidgetItem(mod['name'])
            self.mods_table.setItem(row, 0, name_item)

            # Item name
            item_name_item = QTableWidgetItem(mod.get('item_name', 'Unknown'))
            self.mods_table.setItem(row, 1, item_name_item)

            # Item type
            type_item = QTableWidgetItem(mod.get('item_type', 'Unknown'))
            self.mods_table.setItem(row, 2, type_item)

            # Current ID
            current_id = mod['owner_id'] or 'Not set'
            id_item = QTableWidgetItem(str(current_id))
            id_item.setFont(QFont('Courier New', 9))
            self.mods_table.setItem(row, 3, id_item)

            # Status - compare actual values as strings
            mod_owner_id = str(mod['owner_id']).strip() if mod['owner_id'] else ''
            target_id = str(self.target_owner_id).strip() if self.target_owner_id else ''

            is_fixed = (mod_owner_id and target_id and mod_owner_id == target_id)

            if is_fixed:
                status = '✓ Fixed'
                status_color = QColor('#41a31d')
                correct_count += 1
            else:
                status = '✗ Not Fixed'
                status_color = QColor('#d78521')
                incorrect_count += 1

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QBrush(status_color))
            self.mods_table.setItem(row, 4, status_item)

            # Action button - show for mods that aren't fixed
            if not is_fixed:
                action_btn = QPushButton('Fix')
                action_btn.clicked.connect(lambda checked, m=mod: self.fix_mod(m))
                self.mods_table.setCellWidget(row, 5, action_btn)

        # Update stats
        self.correct_label.setText(f'✓ Fixed: {correct_count}')
        self.incorrect_label.setText(f'✗ Not Fixed: {incorrect_count}')

    def on_mod_row_clicked(self, item):
        """Handle mod row click to show details"""
        row = item.row()
        if row >= 0 and row < len(self.mods):
            mod = self.mods[row]
            dialog = ModDetailsDialog(mod, self)
            dialog.exec_()

    def fix_mod(self, mod):
        """Update a mod's Owner ID"""
        if not self.target_owner_id:
            QMessageBox.warning(self, 'Error', 'Please set a target Owner ID first')
            return

        try:
            config_path = Path(mod['config_path'])
            content = config_path.read_text(encoding='utf-8')

            # Replace or add $OWNER_ID (handles both = and space formats)
            if '$OWNER_ID' in content:
                content = re.sub(r'\$OWNER_ID\s*[=\s]\s*\d+', f'$OWNER_ID {self.target_owner_id}', content)
            else:
                content = f'$OWNER_ID {self.target_owner_id}\n' + content

            config_path.write_text(content, encoding='utf-8')

            # Update the mod in memory
            mod['owner_id'] = self.target_owner_id
            self.update_table()

            QMessageBox.information(self, 'Success', f'Updated {mod["name"]}')

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to update mod: {str(e)}')

    def fix_all_mods(self):
        """Fix all mods that are not fixed"""
        if not self.target_owner_id:
            QMessageBox.warning(self, 'Error', 'Please set a target Owner ID first')
            return

        # Count mods that need fixing
        mods_to_fix = [
            mod for mod in self.mods
            if mod['owner_id'] != self.target_owner_id
        ]

        if not mods_to_fix:
            QMessageBox.information(self, 'All Good!', 'All mods are already fixed!')
            return

        # Confirmation dialog
        count = len(mods_to_fix)
        reply = QMessageBox.question(
            self,
            'Fix All Mods?',
            f'This will update {count} mod(s) with Owner ID: {self.target_owner_id}\n\n'
            'Continue?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Fix all mods
        fixed_count = 0
        failed_count = 0
        failed_mods = []

        for mod in mods_to_fix:
            try:
                config_path = Path(mod['config_path'])
                content = config_path.read_text(encoding='utf-8')

                # Replace or add $OWNER_ID (handles both = and space formats)
                if '$OWNER_ID' in content:
                    content = re.sub(r'\$OWNER_ID\s*[=\s]\s*\d+', f'$OWNER_ID {self.target_owner_id}', content)
                else:
                    content = f'$OWNER_ID {self.target_owner_id}\n' + content

                config_path.write_text(content, encoding='utf-8')
                mod['owner_id'] = self.target_owner_id
                fixed_count += 1

            except Exception as e:
                failed_count += 1
                failed_mods.append((mod['name'], str(e)))

        # Update table to reflect changes
        self.update_table()

        # Show summary
        summary = f'Fixed: {fixed_count}\n'
        if failed_count > 0:
            summary += f'Failed: {failed_count}\n\n'
            for mod_name, error in failed_mods:
                summary += f'• {mod_name}: {error}\n'

        QMessageBox.information(self, 'Fix All Complete', summary)

    def open_catalogue_browser(self):
        """Open the catalogue browser dialog"""
        if not self.game_folder:
            QMessageBox.warning(self, 'Error', 'Please select a game folder first')
            return

        dialog = ModCatalogueDialog(self, self.game_folder)
        dialog.mod_selected.connect(self.on_mod_selected_from_catalogue)
        dialog.exec_()

    def select_and_install_zip(self):
        """Let user manually select a ZIP file to install"""
        if not self.game_folder:
            QMessageBox.warning(self, 'Error', 'Please select a game folder first')
            return

        if not self.target_owner_id:
            QMessageBox.warning(self, 'Error', 'Please set a target Owner ID first')
            return

        # Open file dialog
        zip_file = QFileDialog.getOpenFileName(
            self,
            'Select Mod ZIP File',
            str(Path.home() / 'Downloads'),
            'ZIP Files (*.zip);;All Files (*)'
        )

        if not zip_file[0]:
            return

        zip_path = Path(zip_file[0])
        if not zip_path.exists():
            QMessageBox.warning(self, 'Error', 'File not found')
            return

        # Extract and install
        try:
            # Extract to temp folder first
            import tempfile
            temp_dir = tempfile.mkdtemp()
            extract_temp = Path(temp_dir) / 'extracted'
            extract_temp.mkdir(parents=True, exist_ok=True)

            print(f"[DEBUG] Extracting ZIP: {zip_path}")

            # Extract
            with zipfile.ZipFile(zip_path, 'r') as archive:
                archive.extractall(path=extract_temp)

            # Find the mod folder inside
            extracted_contents = list(extract_temp.iterdir())
            if not extracted_contents:
                raise Exception("ZIP file is empty")

            mod_folder = None
            for item in extracted_contents:
                if item.is_dir():
                    mod_folder = item
                    break

            if not mod_folder:
                raise Exception("No folder found in ZIP file")

            # Use original folder name (user will rename later if needed)
            final_folder_name = mod_folder.name
            workshop_wip = Path(self.game_folder) / 'media_soviet' / 'workshop_wip'
            workshop_wip.mkdir(parents=True, exist_ok=True)
            final_path = workshop_wip / final_folder_name

            # Move to final location
            if final_path.exists():
                import shutil
                shutil.rmtree(final_path)

            mod_folder.rename(final_path)

            # Clean up temp
            import shutil
            shutil.rmtree(temp_dir)

            # Read mod config
            config_path = final_path / 'workshopconfig.ini'
            if not config_path.exists():
                raise Exception("workshopconfig.ini not found in mod")

            # Read metadata
            content = config_path.read_text(encoding='utf-8')
            owner_id_match = re.search(r'\$OWNER_ID\s*[=\s]\s*(\d+)', content)
            owner_id = owner_id_match.group(1).strip() if owner_id_match else None

            item_type_match = re.search(r'\$ITEM_TYPE\s*WORKSHOP_ITEMTYPE_(\w+)', content)
            item_type = item_type_match.group(1) if item_type_match else 'Unknown'

            item_name_match = re.search(r'\$ITEM_NAME\s+"([^"]+)"', content)
            item_name = item_name_match.group(1) if item_name_match else 'Unknown'

            item_desc_match = re.search(r'\$ITEM_DESC\s+"([\s\S]*?)"\s*(?=\$|\Z)', content)
            item_desc = item_desc_match.group(1) if item_desc_match else 'No description'

            mod_data = {
                'name': final_folder_name,
                'path': str(final_path),
                'config_path': str(config_path),
                'owner_id': owner_id,
                'item_type': item_type,
                'item_name': item_name,
                'item_desc': item_desc,
            }

            # Show preview dialog
            dialog = ModDetailsDialog(mod_data, self)
            dialog.exec_()

            # Ask for confirmation
            reply = QMessageBox.question(
                self,
                'Apply Owner ID Fix?',
                f'Apply Owner ID fix to: {mod_data["item_name"]}?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.apply_fix_to_downloaded_mod(mod_data)
            else:
                # User declined, remove the extracted mod
                import shutil
                if final_path.exists():
                    try:
                        shutil.rmtree(final_path)
                        QMessageBox.information(self, 'Info', 'Mod was not installed.')
                    except:
                        pass

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to extract mod: {str(e)}')

    def on_mod_selected_from_catalogue(self, mod_data):
        """Handle mod selected from catalogue"""
        if not self.target_owner_id:
            QMessageBox.warning(self, 'Error', 'Please set a target Owner ID first')
            return

        # Start download in background thread
        self.downloader_thread = ModDownloader(
            mod_data['download_url'],
            mod_data['name'],
            self.game_folder,
            self.target_owner_id,
            mod_data.get('mod_id')  # Pass the Steam mod ID if available
        )
        self.downloader_thread.progress.connect(self.on_download_progress)
        self.downloader_thread.finished.connect(self.on_download_complete)
        self.downloader_thread.error.connect(self.on_download_error)
        self.downloader_thread.start()

        # Show progress dialog
        self.download_progress = QMessageBox(self)
        self.download_progress.setWindowTitle('Downloading Mod')
        self.download_progress.setText(f'Downloading: {mod_data["name"]}...')
        self.download_progress.setStandardButtons(QMessageBox.Cancel)
        self.download_progress.show()

    def on_download_progress(self, mod_name, percent):
        """Update download progress"""
        if hasattr(self, 'download_progress'):
            self.download_progress.setText(f'Downloading: {mod_name}...\n{percent}%')

    def on_download_complete(self, mod_data):
        """Handle download completion"""
        try:
            # Close progress dialog
            if hasattr(self, 'download_progress'):
                self.download_progress.close()

            # Show preview dialog
            dialog = ModDetailsDialog(mod_data, self)
            dialog.exec_()

            # Ask for confirmation
            reply = QMessageBox.question(
                self,
                'Apply Owner ID Fix?',
                f'Apply Owner ID fix to: {mod_data["item_name"]}?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.apply_fix_to_downloaded_mod(mod_data)
            else:
                # User declined, remove the extracted mod
                mod_path = Path(mod_data['path'])
                if mod_path.exists():
                    import shutil
                    try:
                        shutil.rmtree(mod_path)
                        QMessageBox.information(self, 'Info', 'Downloaded mod was removed.')
                    except:
                        pass

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to process downloaded mod: {str(e)}')

    def on_download_error(self, error_msg):
        """Handle download error"""
        if hasattr(self, 'download_progress'):
            self.download_progress.close()
        QMessageBox.critical(self, 'Download Error', error_msg)

    def apply_fix_to_downloaded_mod(self, mod_data):
        """Apply Owner ID fix to downloaded mod"""
        try:
            config_path = Path(mod_data['config_path'])
            content = config_path.read_text(encoding='utf-8')

            # Replace or add $OWNER_ID
            if '$OWNER_ID' in content:
                content = re.sub(r'\$OWNER_ID\s*[=\s]\s*\d+', f'$OWNER_ID {self.target_owner_id}', content)
            else:
                content = f'$OWNER_ID {self.target_owner_id}\n' + content

            config_path.write_text(content, encoding='utf-8')
            mod_data['owner_id'] = self.target_owner_id

            QMessageBox.information(self, 'Success', f'Downloaded and fixed: {mod_data["item_name"]}')

            # Refresh mods list to show new mod
            self.refresh_mods()

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to apply fix: {str(e)}')

    def save_config(self):
        """Save game folder and owner ID to config file"""
        config = {
            'game_folder': self.game_folder,
            'target_owner_id': self.target_owner_id,
        }
        try:
            CONFIG_FILE.write_text(json.dumps(config, indent=2))
        except Exception as e:
            print(f"Warning: Could not save config: {e}")

    def load_config(self):
        """Load game folder and owner ID from config file"""
        try:
            if CONFIG_FILE.exists():
                config = json.loads(CONFIG_FILE.read_text())
                self.game_folder = config.get('game_folder')
                loaded_owner_id = config.get('target_owner_id')
                # Ensure it's a clean string, not None
                self.target_owner_id = str(loaded_owner_id).strip() if loaded_owner_id else None
        except Exception as e:
            print(f"Warning: Could not load config: {e}")


def main():
    app = QApplication(sys.argv)
    window = ModInstallerApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

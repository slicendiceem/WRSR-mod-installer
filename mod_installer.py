import sys
import os
import json
import re
import tempfile
import zipfile
from pathlib import Path
import requests
from html.parser import HTMLParser
import asyncio
from playwright.async_api import async_playwright
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
    progress = pyqtSignal(str, int)  # mod_name, percent complete (file download)
    prep_progress = pyqtSignal(str, int)  # mod_name, percent complete (link preparation)
    finished = pyqtSignal(dict)       # mod_data dict with extracted info
    error = pyqtSignal(str)

    def __init__(self, download_url, mod_name, game_folder, target_owner_id, mod_id=None, description="", image_url=None):
        super().__init__()
        self.download_url = download_url
        self.mod_name = mod_name
        self.game_folder = game_folder
        self.target_owner_id = target_owner_id
        self.mod_id = mod_id  # Steam mod ID to rename folder to
        self.description = description  # Skymods description (optional)
        self.image_url = image_url  # Skymods image URL (optional)
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

            # First, read the config to get the actual $ITEM_ID
            temp_config_path = mod_folder / 'workshopconfig.ini'
            item_id = None
            if temp_config_path.exists():
                content = temp_config_path.read_text(encoding='utf-8')
                item_id_match = re.search(r'\$ITEM_ID\s+(\d+)', content)
                item_id = item_id_match.group(1).strip() if item_id_match else None
                print(f"[DEBUG] Found $ITEM_ID in config: {item_id}")

            # Determine final folder name - use $ITEM_ID from config, fallback to original name
            final_folder_name = item_id if item_id else mod_folder.name
            print(f"[DEBUG] Using folder name: {final_folder_name}")
            final_path = workshop_wip / final_folder_name

            # Move mod folder to workshop_wip with new name
            import shutil
            if final_path.exists():
                shutil.rmtree(final_path)
            # Use shutil.move() instead of rename() to support cross-drive moves
            shutil.move(str(mod_folder), str(final_path))

            # Read extracted mod config to get metadata
            mod_data = self._read_mod_config(final_path)
            mod_data['path'] = str(final_path)

            # Use Skymods description and image if provided, otherwise use local config
            if self.description:
                mod_data['item_desc'] = self.description
            if self.image_url:
                mod_data['image_url'] = self.image_url

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
        """Download file with progress updates, handling modsbase with browser automation"""
        try:
            print(f"[DEBUG] Starting download from: {url}")

            # Special handling for modsbase URLs - download directly through browser
            if 'modsbase.com' in url and url.endswith('.html'):
                print(f"[DEBUG] Detected modsbase redirect page, using browser download...")
                success = self._download_file_with_browser(url, dest_path)
                if success:
                    file_size = dest_path.stat().st_size
                    print(f"[DEBUG] Download complete. File size: {file_size} bytes")

                    # Check if we downloaded HTML by mistake
                    if file_size < 100000:
                        first_bytes = dest_path.read_bytes()[:50]
                        if b'<!DOCTYPE' in first_bytes or b'<html' in first_bytes or b'No file' in first_bytes:
                            print(f"[DEBUG] ERROR: Downloaded file appears to be HTML, not a ZIP")
                            raise Exception("Downloaded file is HTML/error page, not a valid ZIP archive")
                    return

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
            if file_size < 100000:
                first_bytes = dest_path.read_bytes()[:50]
                if b'<!DOCTYPE' in first_bytes or b'<html' in first_bytes:
                    print(f"[DEBUG] ERROR: Downloaded file appears to be HTML, not a ZIP")
                    raise Exception("Downloaded file is HTML, not a valid ZIP archive")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Download failed: {str(e)}")

    def _download_file_with_browser(self, modsbase_url, dest_path):
        """Download file directly through browser to maintain session and avoid link expiration"""
        try:
            print(f"[DEBUG] Opening modsbase page in browser: {modsbase_url}")

            async def download_file():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context()
                    page = await context.new_page()

                    print(f"[DEBUG] Loading page...")
                    # Emit prep progress: page loading
                    self.prep_progress.emit(self.mod_name, 10)
                    await page.goto(modsbase_url, wait_until='networkidle')

                    print(f"[DEBUG] Page loaded. Waiting 5 seconds for dynamic content...")
                    # Emit prep progress: waiting for dynamic content
                    self.prep_progress.emit(self.mod_name, 25)
                    await page.wait_for_timeout(5000)

                    # Try to find and click the "Create Download Link" button
                    try:
                        print(f"[DEBUG] Looking for 'Create Download Link' button...")
                        buttons = await page.query_selector_all('button')

                        button_found = False
                        if buttons:
                            print(f"[DEBUG] Found {len(buttons)} buttons total")
                            for btn in buttons:
                                text = await btn.text_content()
                                print(f"[DEBUG] Button text: '{text}'")
                                if text and ('create' in text.lower() or 'download' in text.lower()):
                                    print(f"[DEBUG] Clicking button: {text}")
                                    # Emit prep progress: found and clicking button
                                    self.prep_progress.emit(self.mod_name, 40)
                                    await btn.click()
                                    button_found = True
                                    # Wait for page to update with new download link
                                    await page.wait_for_timeout(3000)
                                    break

                        if button_found:
                            # After clicking, look for the download link that should appear
                            print(f"[DEBUG] Looking for download link after button click...")
                            try:
                                # Wait for a real .zip link (not .html) to appear
                                # Emit prep progress: generating download link
                                self.prep_progress.emit(self.mod_name, 75)
                                await page.wait_for_function(
                                    """() => {
                                        const links = Array.from(document.querySelectorAll('a'))
                                            .filter(a => a.href && a.href.includes('.zip') && !a.href.endsWith('.html'));
                                        return links.length > 0;
                                    }""",
                                    timeout=10000
                                )

                                # Now get and click the download link
                                links = await page.query_selector_all('a[href*=".zip"]')
                                print(f"[DEBUG] Found {len(links)} links with .zip after button click")

                                for link in links:
                                    href = await link.get_attribute('href')
                                    if href and '.zip' in href.lower() and not href.endswith('.html'):
                                        print(f"[DEBUG] Clicking generated download link: {href}")
                                        # Emit prep progress: link ready, starting download
                                        self.prep_progress.emit(self.mod_name, 100)
                                        async with page.expect_download(timeout=30000) as download_info:
                                            await link.click()
                                            await page.wait_for_timeout(1000)

                                        download = await download_info.value
                                        print(f"[DEBUG] Download started: {download.suggested_filename}")
                                        # Emit file download progress
                                        self.progress.emit(self.mod_name, 10)
                                        await download.save_as(dest_path)
                                        print(f"[DEBUG] File saved to: {dest_path}")
                                        # Emit completion
                                        self.progress.emit(self.mod_name, 100)
                                        await browser.close()
                                        return True

                            except Exception as e:
                                print(f"[DEBUG] Error waiting for generated link: {str(e)}")

                        else:
                            print(f"[DEBUG] No click button found, trying fallback with direct links...")
                            # Emit prep progress: trying fallback
                            self.prep_progress.emit(self.mod_name, 50)

                        # Fallback: try to click any download link
                        links = await page.query_selector_all('a[href*=".zip"]')
                        print(f"[DEBUG] Found {len(links)} links with .zip in href (fallback)")

                        if links:
                            for link in links:
                                href = await link.get_attribute('href')
                                if href and '.zip' in href.lower() and not href.endswith('.html'):
                                    print(f"[DEBUG] Clicking download link via fallback: {href}")
                                    # Emit prep progress: ready for fallback download
                                    self.prep_progress.emit(self.mod_name, 100)
                                    async with page.expect_download(timeout=30000) as download_info:
                                        await link.click()
                                        await page.wait_for_timeout(1000)

                                    download = await download_info.value
                                    print(f"[DEBUG] Download started: {download.suggested_filename}")
                                    # Emit file download progress
                                    self.progress.emit(self.mod_name, 10)
                                    await download.save_as(dest_path)
                                    print(f"[DEBUG] File saved to: {dest_path}")
                                    # Emit completion
                                    self.progress.emit(self.mod_name, 100)
                                    await browser.close()
                                    return True

                    except Exception as e:
                        print(f"[DEBUG] Error during download attempt: {str(e)}")

                    await browser.close()
                    return False

            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(download_file())
            loop.close()

            return success

        except Exception as e:
            print(f"[DEBUG] Error in browser download: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

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
        image_label = QLabel()
        pixmap = None

        # First try: use Skymods image URL if available
        if mod.get('image_url'):
            try:
                print(f"[DEBUG] Loading Skymods image from: {mod['image_url']}")
                response = requests.get(mod['image_url'], timeout=10)
                if response.status_code == 200:
                    from io import BytesIO
                    image_data = BytesIO(response.content)
                    pixmap = QPixmap()
                    pixmap.loadFromData(image_data.getvalue())
                    print(f"[DEBUG] Skymods image loaded successfully")
            except Exception as e:
                print(f"[DEBUG] Failed to load Skymods image: {str(e)}")

        # Fallback: use local previewimage.png if Skymods image not available
        if not pixmap:
            image_path = Path(mod['path']) / 'previewimage.png'
            if image_path.exists():
                pixmap = QPixmap(str(image_path))

        # Display the image
        if pixmap and not pixmap.isNull():
            # Scale image to fit but maintain aspect ratio, with max height
            scaled_pixmap = pixmap.scaledToWidth(300, Qt.SmoothTransformation)
            if scaled_pixmap.height() > 200:
                scaled_pixmap = pixmap.scaledToHeight(200, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_label)
        else:
            no_image = QLabel("No preview image available")
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


class DetailsFetchThread(QThread):
    """Background thread for fetching mod details without freezing"""
    details_fetched = pyqtSignal(dict)  # Mod with details
    error = pyqtSignal(str)

    def __init__(self, mod, catalogue_dialog):
        super().__init__()
        self.mod = mod
        self.catalogue_dialog = catalogue_dialog

    def run(self):
        try:
            mod_details = self.catalogue_dialog._extract_download_link(self.mod['url'])
            self.mod['download_url'] = mod_details['download_url']
            self.mod['description'] = mod_details['description']
            self.mod['image_url'] = mod_details['image_url']
            self.mod['prerequisites'] = mod_details['prerequisites']
            self.details_fetched.emit(self.mod)
        except Exception as e:
            self.error.emit(str(e))


class PrerequisiteFetchThread(QThread):
    """Background thread for fetching prerequisite mod details"""
    prerequisites_fetched = pyqtSignal(list)  # list of (prereq_info, mod_data)
    error = pyqtSignal(str)

    def __init__(self, prerequisites, catalogue_dialog):
        super().__init__()
        self.prerequisites = prerequisites
        self.catalogue_dialog = catalogue_dialog

    def run(self):
        try:
            fetched_mods = []
            for prereq_info in self.prerequisites:
                # Use the catalogue dialog's search method to get prerequisite with full details
                prereq_mod = self.catalogue_dialog._search_prerequisite(prereq_info)
                if prereq_mod:
                    fetched_mods.append((prereq_info, prereq_mod))

            self.prerequisites_fetched.emit(fetched_mods)
        except Exception as e:
            self.error.emit(str(e))


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
            import html as html_module

            post_pattern = r'<h[2-3][^>]*class="[^"]*post-title[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a'
            matches = re.finditer(post_pattern, html, re.IGNORECASE | re.DOTALL)

            for match in matches:
                mod_url = match.group(1)
                mod_name = match.group(2).strip()

                if mod_url and mod_name:
                    # Decode HTML entities in mod name (e.g., &#8217; -> ')
                    mod_name = html_module.unescape(mod_name)

                    # Extract Steam mod ID from URL (e.g., https://catalogue.smods.ru/archives/421998 -> 421998)
                    mod_id_match = re.search(r'/archives/(\d+)', mod_url)
                    mod_id = mod_id_match.group(1) if mod_id_match else None

                    mods.append({
                        'name': mod_name[:100],
                        'url': mod_url,
                        'mod_id': mod_id,
                        'download_url': None,
                        'description': '',
                        'image_url': None,
                        'prerequisites': [],
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
                            'description': '',
                            'image_url': None,
                            'prerequisites': [],
                        })

        except Exception as e:
            pass

        return mods


class ModDetailsPopup(QDialog):
    """Popup dialog to show mod details"""
    add_to_queue = pyqtSignal(dict)  # Emits mod data when user clicks Add

    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        import html as html_module

        # Decode mod name for display
        display_name = html_module.unescape(mod["name"])

        self.setWindowTitle(f'{display_name} - Details')
        self.setGeometry(100, 100, 600, 700)
        self.setModal(True)

        layout = QVBoxLayout()

        # Mod name
        name_label = QLabel(f'<b style="font-size: 14pt">{display_name}</b>')
        layout.addWidget(name_label)

        # Create scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        # Image
        if mod.get('image_url'):
            try:
                response = requests.get(mod['image_url'], timeout=10)
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)

                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaledToWidth(500, Qt.SmoothTransformation)
                    image_label = QLabel()
                    image_label.setPixmap(scaled_pixmap)
                    image_label.setAlignment(Qt.AlignCenter)
                    container_layout.addWidget(image_label)
            except Exception as e:
                print(f"[DEBUG] Failed to load popup image: {str(e)}")

        # Description
        if mod.get('description'):
            desc_label = QLabel('<b>Description:</b>')
            container_layout.addWidget(desc_label)
            desc_text = QLabel(mod['description'])
            desc_text.setWordWrap(True)
            # Preserve paragraph breaks and formatting
            desc_text.setText(mod['description'].replace('\n', '<br>'))
            container_layout.addWidget(desc_text)
            container_layout.addSpacing(10)

        # Prerequisites
        if mod.get('prerequisites'):
            prereq_label = QLabel('<b>Requirements:</b>')
            container_layout.addWidget(prereq_label)
            for prereq in mod['prerequisites']:
                # Extract name if it's stored as a tuple (name, steam_id)
                if isinstance(prereq, tuple):
                    prereq_name = prereq[0]
                else:
                    prereq_name = prereq
                prereq_item = QLabel(f'• {prereq_name}')
                prereq_item.setWordWrap(True)
                container_layout.addWidget(prereq_item)
            container_layout.addSpacing(10)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        add_btn = QPushButton('➜ Add to Queue')
        add_btn.setStyleSheet('background-color: #4a90e2; color: white; font-weight: bold;')
        add_btn.clicked.connect(self.on_add_clicked)
        btn_layout.addWidget(add_btn)

        close_btn = QPushButton('Cancel')
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def on_add_clicked(self):
        """Emit signal and close when user clicks Add"""
        self.add_to_queue.emit(self.mod)
        self.close()


class ModCatalogueDialog(QDialog):
    """Dialog for searching and downloading mods from Skymods"""
    mod_selected = pyqtSignal(dict)  # Emits mod data with download_url

    SKYMODS_BASE_URL = 'https://catalogue.smods.ru'

    def __init__(self, parent=None, game_folder=None):
        super().__init__(parent)
        self.setWindowTitle('Search and Download Mods from Skymods')
        self.setGeometry(100, 100, 1400, 750)
        self.search_results = []
        self.download_queue = []  # Mods selected for download
        self.selected_result_mod = None
        self.selected_queue_mod = None
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

        # Status label
        self.results_label = QLabel('Enter search term and click Search')
        layout.addWidget(self.results_label)

        # Main section: Three columns (Results | Arrows | Download Queue)
        main_layout = QHBoxLayout()

        # LEFT: Search Results
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel('📋 Available Mods:'))

        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.on_result_selected)
        self.results_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_list.itemDoubleClicked.connect(self.on_add_to_queue)
        left_layout.addWidget(self.results_list)

        main_layout.addLayout(left_layout, 1)

        # CENTER: Arrow buttons
        center_layout = QVBoxLayout()
        center_layout.addStretch()

        add_btn = QPushButton('➜\nAdd')
        add_btn.setMaximumWidth(50)
        add_btn.setMinimumHeight(60)
        add_btn.clicked.connect(self.on_add_to_queue)
        center_layout.addWidget(add_btn)

        remove_btn = QPushButton('⬅\nRemove')
        remove_btn.setMaximumWidth(50)
        remove_btn.setMinimumHeight(60)
        remove_btn.clicked.connect(self.on_remove_from_queue)
        center_layout.addWidget(remove_btn)

        center_layout.addStretch()
        main_layout.addLayout(center_layout, 0)

        # RIGHT: Download Queue + Preview
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel('📥 Download Queue:'))

        # Queue list
        self.queue_list = QListWidget()
        self.queue_list.itemClicked.connect(self.on_queue_selected)
        self.queue_list.setSelectionMode(QAbstractItemView.SingleSelection)
        right_layout.addWidget(self.queue_list, 1)

        # Preview panel
        preview_label = QLabel('Preview:')
        right_layout.addWidget(preview_label)

        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setMaximumHeight(300)
        preview_layout.addWidget(self.preview_image)

        self.preview_text = QLabel('Select a mod from queue to see details')
        self.preview_text.setWordWrap(True)
        self.preview_text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.preview_text.setOpenExternalLinks(True)
        preview_layout.addWidget(self.preview_text)

        preview_layout.addStretch()
        preview_scroll.setWidget(preview_container)
        right_layout.addWidget(preview_scroll, 1)  # Give scroll area stretch factor

        main_layout.addLayout(right_layout, 1)

        layout.addLayout(main_layout, 1)

        # Bottom: Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        download_btn = QPushButton('📥 Download All in Queue')
        download_btn.setStyleSheet('background-color: #4a90e2; color: white; font-weight: bold;')
        download_btn.clicked.connect(self.on_download_all)
        btn_layout.addWidget(download_btn)

        # Processing indicator for prerequisites
        self.processing_label = QLabel('')
        self.processing_label.setStyleSheet('color: #FF9800; font-weight: bold;')
        btn_layout.addWidget(self.processing_label)

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
        self.search_results.clear()  # Clear old search results
        self.selected_result_mod = None

        # Cache installed mod names ONCE before search (to avoid disk I/O on every page)
        self.installed_mod_cache = set()
        if self.game_folder:
            workshop_path = Path(self.game_folder) / 'media_soviet' / 'workshop_wip'
            if workshop_path.exists():
                for mod_folder in workshop_path.iterdir():
                    if mod_folder.is_dir():
                        config_path = mod_folder / 'workshopconfig.ini'
                        if config_path.exists():
                            try:
                                content = config_path.read_text(encoding='utf-8')
                                # Extract $ITEM_NAME
                                name_match = re.search(r'\$ITEM_NAME\s+"([^"]+)"', content)
                                if name_match:
                                    item_name = name_match.group(1).strip()
                                    self.installed_mod_cache.add(item_name.lower())
                            except Exception as e:
                                print(f"[DEBUG] Failed to read mod config: {str(e)}")

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
        """Add mods to the results list immediately as they're found"""
        # Use cached installed mod names (set in perform_search)
        installed_mod_names = self.installed_mod_cache if hasattr(self, 'installed_mod_cache') else set()

        # Helper function to normalize names for comparison
        def normalize_name(name):
            return re.sub(r'[\s_\-]+', '', name).lower()

        for mod in mods:
            self.search_results.append(mod)

            # Check if mod is already installed by comparing names
            is_installed = False
            normalized_search_name = normalize_name(mod['name'])

            for installed_name in installed_mod_names:
                normalized_installed_name = normalize_name(installed_name)
                # Check for exact match or substring match
                if normalized_search_name == normalized_installed_name or \
                   normalized_search_name in normalized_installed_name or \
                   normalized_installed_name in normalized_search_name:
                    is_installed = True
                    break

            # Determine status and color
            if is_installed:
                status_text = "✓ Already Installed"
                status_color = QColor('#41a31d')  # Green
            elif mod.get('download_url'):
                status_text = "✓ Available"
                status_color = QColor('#2196F3')  # Blue
            else:
                status_text = "⚠ No download"
                status_color = QColor('#FF9800')  # Orange

            display_name = f"{mod['name']} [{status_text}]"
            item = QListWidgetItem(display_name)
            item.setForeground(QBrush(status_color))
            item.setFont(QFont('Arial', 10))
            self.results_list.addItem(item)

    def on_search_complete(self, results):
        """Handle search completion"""
        # Results already added via on_mods_found, just update label
        if self.search_results:
            self.results_label.setText(f'Found {len(self.search_results)} mod(s) - Search complete')
        else:
            search_term = self.search_input.text().strip()
            self.results_label.setText(f'No mods found for "{search_term}"')

    def on_search_error(self, error_msg):
        """Handle search error"""
        self.results_label.setText('Error searching Skymods')

    def _parse_results_page(self, html):
        """Parse a single Skymods search results page - used by both ModSearchThread and prerequisite searches"""
        mods = []
        try:
            import re
            import html as html_module

            post_pattern = r'<h[2-3][^>]*class="[^"]*post-title[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a'
            matches = re.finditer(post_pattern, html, re.IGNORECASE | re.DOTALL)

            for match in matches:
                mod_url = match.group(1)
                mod_name = match.group(2).strip()

                if mod_url and mod_name:
                    # Decode HTML entities in mod name (e.g., &#8217; -> ')
                    mod_name = html_module.unescape(mod_name)

                    # Extract Steam mod ID from URL (e.g., https://catalogue.smods.ru/archives/421998 -> 421998)
                    mod_id_match = re.search(r'/archives/(\d+)', mod_url)
                    mod_id = mod_id_match.group(1) if mod_id_match else None

                    mods.append({
                        'name': mod_name[:100],
                        'url': mod_url,
                        'mod_id': mod_id,
                        'download_url': None,
                        'description': '',
                        'image_url': None,
                        'prerequisites': [],
                    })

        except Exception as e:
            pass

        return mods

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

            # Extract description (look for actual description after "Description:" label)
            description = ""
            # Try multiple patterns for different page layouts
            desc_patterns = [
                r'Description:\s*(?:</[^>]+>)*\s*(.*?)(?=<[bB]|<[hH]|</[dD]|$)',  # After Description: label
                r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>',
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            ]

            for pattern in desc_patterns:
                desc_match = re.search(pattern, response.text, re.IGNORECASE | re.DOTALL)
                if desc_match:
                    description = desc_match.group(1)
                    # Strip HTML tags
                    description = re.sub(r'<[^>]+>', '', description)
                    # Remove author/date metadata at the start
                    description = re.sub(r'^[^a-zA-Z0-9]*(?:Author|By|Date|Created|Posted|Upload):[^\n]*\n*', '', description, flags=re.IGNORECASE | re.MULTILINE)
                    # Remove the rating reminder
                    description = re.sub(r'if you liked.*?steam.*?\n', '', description, flags=re.IGNORECASE | re.DOTALL)
                    # Normalize whitespace: preserve paragraph breaks
                    description = re.sub(r' +', ' ', description)  # Multiple spaces to single
                    description = re.sub(r'\n\s*\n', '\n\n', description)  # Preserve double newlines
                    description = description.strip()

                    # Only use if we got substantial content
                    if description and len(description) > 20:
                        break

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

            # Extract prerequisites from "Required items" section
            prerequisites = []
            # Look for the skymods-single-section div with "Required items"
            prereq_section_pattern = r'<div[^>]*class="[^"]*skymods-single-section[^"]*"[^>]*>.*?<h5>Required items:</h5>(.*?)</div>'
            prereq_section_match = re.search(prereq_section_pattern, response.text, re.IGNORECASE | re.DOTALL)

            if prereq_section_match:
                section_text = prereq_section_match.group(1)
                # Extract all links with prerequisite names AND their Steam IDs
                # Look for: <a href="https://catalogue.smods.ru/?s=STEAMID">ModName</a>
                link_pattern = r'<a[^>]*href="https://catalogue\.smods\.ru/\?s=(\d+)"[^>]*>([^<]+)</a>'
                for link_match in re.finditer(link_pattern, section_text):
                    steam_id = link_match.group(1).strip()
                    prereq_name = link_match.group(2).strip()
                    # Store as tuple: (name, steam_id)
                    if steam_id and prereq_name:
                        prerequisites.append((prereq_name, steam_id))

            # Fallback: Also check for old format "Requires:" or "Prerequisites:"
            if not prerequisites:
                prereq_pattern = r'(?:Requires?|Depends?|Prerequisites?):\s*([^<\n]+)'
                prereq_matches = re.finditer(prereq_pattern, response.text, re.IGNORECASE)
                for match in prereq_matches:
                    prereq_text = match.group(1).strip()
                    if prereq_text:
                        # Store as tuple with None for steam_id (fallback format)
                        prerequisites.append((prereq_text, None))

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
        """Show details in preview panel when mod is selected from results"""
        row = self.results_list.row(item)
        if 0 <= row < len(self.search_results):
            self.selected_result_mod = self.search_results[row]

            # Update preview panel immediately with basic info
            preview = f"<b>{self.selected_result_mod['name']}</b><br><br>"
            preview += "<i>Loading details...</i>"
            self.preview_text.setText(preview)
            self.preview_image.setPixmap(QPixmap())

            # Fetch details if not already fetched
            if self.selected_result_mod['download_url'] is None:
                # Fetch details in background to avoid freezing
                self.details_fetch_thread = DetailsFetchThread(self.selected_result_mod, self)
                self.details_fetch_thread.details_fetched.connect(self.on_details_fetched)
                self.details_fetch_thread.error.connect(self.on_details_error)
                self.details_fetch_thread.start()
            else:
                # Already have details, just update preview
                self.on_details_fetched(self.selected_result_mod)

    def on_details_fetched(self, mod):
        """Update preview panel with fetched details"""
        # Load and display image
        if mod.get('image_url'):
            try:
                response = requests.get(mod['image_url'], timeout=10)
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                    self.preview_image.setPixmap(scaled_pixmap)
            except Exception as e:
                print(f"[DEBUG] Failed to load preview image: {str(e)}")

        # Build preview text
        preview = f"<b>{mod['name']}</b><br><br>"

        if mod.get('description'):
            preview += f"<b>Description:</b><br>{mod['description'].replace(chr(10), '<br>')}<br><br>"

        if mod.get('prerequisites'):
            preview += f"<b>Requirements:</b><br>"
            for prereq in mod['prerequisites']:
                # Extract name if it's stored as a tuple (name, steam_id)
                if isinstance(prereq, tuple):
                    prereq_name = prereq[0]
                else:
                    prereq_name = prereq
                preview += f"• {prereq_name}<br>"

        if mod.get('download_url'):
            preview += "<br>✓ Ready to download"
        else:
            preview += "<br>⚠ No download link"

        self.preview_text.setText(preview)

    def on_details_error(self, error_msg):
        """Handle details fetching error"""
        preview = f"<b>{self.selected_result_mod['name']}</b><br><br>"
        preview += f"<i>Error loading details: {error_msg}</i>"
        self.preview_text.setText(preview)

    def on_add_to_queue(self, mod=None):
        """Add mod to download queue (from button click or popup signal)"""
        # If called from popup signal, mod will be passed as parameter
        if mod:
            selected_mod = mod
        else:
            # If called from button, use selected_result_mod
            selected_mod = self.selected_result_mod

        if not selected_mod:
            QMessageBox.warning(self, 'Error', 'Please select a mod from the results')
            return

        # Check if mod is already in queue
        for queued_mod in self.download_queue:
            if queued_mod.get('mod_id') == selected_mod.get('mod_id') and \
               queued_mod.get('mod_id') is not None:
                QMessageBox.warning(self, 'Already in Queue', f'{selected_mod["name"]} is already in the download queue')
                return

        # Add to queue
        self.download_queue.append(selected_mod)

        # Update queue display
        display_name = selected_mod['name']
        item = QListWidgetItem(display_name)
        item.setFont(QFont('Arial', 10))
        self.queue_list.addItem(item)

        # Fetch prerequisites in background if they exist
        if selected_mod.get('prerequisites'):
            self.current_mod_for_prereqs = selected_mod
            # Show processing indicator
            self.processing_label.setText('⏳ Processing Prerequisites...')
            # Start background thread to fetch prerequisites
            self.prereq_thread = PrerequisiteFetchThread(selected_mod['prerequisites'], self)
            self.prereq_thread.prerequisites_fetched.connect(self.on_prerequisites_fetched)
            self.prereq_thread.error.connect(self.on_prerequisite_error)
            self.prereq_thread.start()
        else:
            # Clear selection only if no prerequisites
            self.selected_result_mod = None
            self.results_list.clearSelection()

    def on_prerequisites_fetched(self, fetched_mods):
        """Handle background prerequisite fetching completion"""
        added_prereqs = []
        missing_prereqs = []

        for prereq_info, prereq_mod in fetched_mods:
            # Extract name from tuple if needed
            if isinstance(prereq_info, tuple):
                prereq_name = prereq_info[0]
            else:
                prereq_name = prereq_info

            if prereq_mod:
                # Check if not already in queue
                already_queued = False
                for queued in self.download_queue:
                    if queued.get('mod_id') == prereq_mod.get('mod_id') and queued.get('mod_id') is not None:
                        already_queued = True
                        break

                if not already_queued:
                    # Add prerequisite to queue
                    self.download_queue.append(prereq_mod)
                    prereq_item = QListWidgetItem(prereq_mod['name'])
                    prereq_item.setFont(QFont('Arial', 10))
                    self.queue_list.addItem(prereq_item)
                    added_prereqs.append(prereq_name)
            else:
                missing_prereqs.append(prereq_name)

        # Notify user about what was added
        if added_prereqs or missing_prereqs:
            main_mod_name = self.current_mod_for_prereqs.get('name', 'Mod')
            message = f'Added: {main_mod_name}'
            if added_prereqs:
                message += f'\n\nAutomatically added prerequisites:\n' + '\n'.join([f'✓ {p}' for p in added_prereqs])
            if missing_prereqs:
                message += f'\n\nPrerequisites not found on Skymods:\n' + '\n'.join([f'✗ {p}' for p in missing_prereqs])
            QMessageBox.information(self, 'Prerequisites', message)

        # Hide processing indicator
        self.processing_label.setText('')

        # Clear selection
        self.selected_result_mod = None
        self.results_list.clearSelection()

    def on_prerequisite_error(self, error_msg):
        """Handle prerequisite fetching error"""
        # Still add the main mod, just notify about the error
        main_mod_name = self.current_mod_for_prereqs.get('name', 'Mod') if hasattr(self, 'current_mod_for_prereqs') else 'Mod'
        QMessageBox.warning(self, 'Prerequisite Error',
                           f'Added: {main_mod_name}\n\nError fetching prerequisites: {error_msg}')

        # Hide processing indicator
        self.processing_label.setText('')

        self.selected_result_mod = None
        self.results_list.clearSelection()

    def _search_prerequisite(self, prereq_info):
        """Search Skymods for a prerequisite and return the first result

        Args:
            prereq_info: tuple of (prereq_name, steam_id) or just prereq_name string
        """
        try:
            # Handle both tuple format (name, steam_id) and string format (name only)
            if isinstance(prereq_info, tuple):
                prereq_name, steam_id = prereq_info
            else:
                prereq_name = prereq_info
                steam_id = None

            # If we have a Steam ID, search by that (more reliable)
            if steam_id:
                url = f'{self.SKYMODS_BASE_URL}/?s={steam_id}&app=784150'
            else:
                # Fallback to searching by name
                url = f'{self.SKYMODS_BASE_URL}/?s={prereq_name}&app=784150'

            response = requests.get(url, timeout=20)
            response.raise_for_status()

            # Parse results page
            mods = self._parse_results_page(response.text)
            if mods:
                # Get the first result
                prereq_mod = mods[0]

                # Extract download link details for this mod
                mod_details = self._extract_download_link(prereq_mod['url'])
                prereq_mod['download_url'] = mod_details['download_url']
                prereq_mod['description'] = mod_details['description']
                prereq_mod['image_url'] = mod_details['image_url']
                prereq_mod['prerequisites'] = mod_details['prerequisites']

                return prereq_mod

            return None
        except Exception as e:
            print(f"[DEBUG] Failed to search for prerequisite '{prereq_info}': {str(e)}")
            return None

    def on_remove_from_queue(self):
        """Remove selected mod from download queue"""
        if not self.selected_queue_mod:
            QMessageBox.warning(self, 'Error', 'Please select a mod from the queue')
            return

        row = self.queue_list.row(self.queue_list.currentItem())
        if 0 <= row < len(self.download_queue):
            removed_mod = self.download_queue.pop(row)
            self.queue_list.takeItem(row)

            # Reset preview
            self.preview_image.setPixmap(QPixmap())
            self.preview_text.setText('Select a mod from queue to see details')
            self.selected_queue_mod = None

    def on_queue_selected(self, item):
        """Handle selection in the download queue - show preview"""
        row = self.queue_list.row(item)
        if 0 <= row < len(self.download_queue):
            mod = self.download_queue[row]
            self.selected_queue_mod = mod

            # Load and display image
            if mod.get('image_url'):
                try:
                    response = requests.get(mod['image_url'], timeout=10)
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)

                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                        self.preview_image.setPixmap(scaled_pixmap)
                except Exception as e:
                    print(f"[DEBUG] Failed to load preview image: {str(e)}")

            # Build preview text
            preview = f"<b>{mod['name']}</b><br><br>"

            if mod.get('description'):
                preview += f"<b>Description:</b><br>{mod['description']}<br><br>"

            if mod.get('prerequisites'):
                preview += f"<b>Prerequisites:</b><br>"
                for prereq in mod['prerequisites']:
                    # Extract name if it's stored as a tuple (name, steam_id)
                    if isinstance(prereq, tuple):
                        prereq_name = prereq[0]
                    else:
                        prereq_name = prereq
                    preview += f"• {prereq_name}<br>"

            if mod.get('download_url'):
                preview += "<br>✓ Ready to download"
            else:
                preview += "<br>⚠ No download link"

            self.preview_text.setText(preview)

    def on_download_all(self):
        """Download all mods in the queue"""
        if not self.download_queue:
            QMessageBox.warning(self, 'Error', 'Please add mods to the queue first')
            return

        # Check for mods without download links
        no_download_mods = [m for m in self.download_queue if not m.get('download_url')]
        if no_download_mods:
            no_download_names = ', '.join([m['name'] for m in no_download_mods])
            reply = QMessageBox.warning(
                self, 'Missing Downloads',
                f'These mods do not have download links:\n\n{no_download_names}\n\n'
                f'Remove them or continue with the remaining mods?',
                QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Discard
            )
            if reply == QMessageBox.Cancel:
                return
            # Filter out mods without download links
            self.download_queue = [m for m in self.download_queue if m.get('download_url')]
            if not self.download_queue:
                return

        # Check if any mod is already installed by comparing names
        already_installed = []

        # Use cached installed mod names
        installed_mod_names = self.installed_mod_cache if hasattr(self, 'installed_mod_cache') else set()

        # Helper function to normalize names for comparison
        def normalize_name(name):
            return re.sub(r'[\s_\-]+', '', name).lower()

        for mod in self.download_queue:
            normalized_mod_name = normalize_name(mod['name'])

            for installed_name in installed_mod_names:
                normalized_installed = normalize_name(installed_name)
                if normalized_mod_name == normalized_installed or \
                   normalized_mod_name in normalized_installed or \
                   normalized_installed in normalized_mod_name:
                    already_installed.append(mod['name'])
                    break

        if already_installed:
            reply = QMessageBox.question(
                self, 'Already Installed',
                f'These mods are already installed:\n\n' + '\n'.join([f'• {m}' for m in already_installed]) +
                '\n\nDo you want to re-download and reinstall them?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                # Filter out already installed mods
                self.download_queue = [m for m in self.download_queue if m['name'] not in already_installed]
                if not self.download_queue:
                    return

        # Emit signal for each mod in queue
        for mod in self.download_queue:
            self.mod_selected.emit(mod)

        self.close()


class DownloadProgressDialog(QDialog):
    """Custom dialog showing download progress with three progress bars"""
    def __init__(self, parent=None, total_mods=1):
        super().__init__(parent)
        self.total_mods = total_mods
        self.current_mod_index = 0

        self.setWindowTitle('Downloading Mods')
        self.setGeometry(200, 200, 500, 280)
        self.setModal(True)

        layout = QVBoxLayout()

        # Mod name label
        self.mod_name_label = QLabel('Initializing...')
        self.mod_name_label.setStyleSheet('font-weight: bold; font-size: 11pt;')
        layout.addWidget(self.mod_name_label)

        # Queue progress bar
        queue_label = QLabel('Queue Progress:')
        layout.addWidget(queue_label)
        self.queue_progress = QProgressBar()
        self.queue_progress.setRange(0, total_mods)
        self.queue_progress.setValue(0)
        layout.addWidget(self.queue_progress)

        # Link preparation progress bar
        prep_label = QLabel('Link Preparation:')
        layout.addWidget(prep_label)
        self.prep_progress = QProgressBar()
        self.prep_progress.setRange(0, 100)
        self.prep_progress.setValue(0)
        layout.addWidget(self.prep_progress)

        # Download progress bar
        download_label = QLabel('File Download:')
        layout.addWidget(download_label)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)

        # Status label
        self.status_label = QLabel('')
        layout.addWidget(self.status_label)

        # Cancel button
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.setLayout(layout)

    def update_mod_name(self, mod_name, current_index):
        """Update the mod being downloaded"""
        self.current_mod_index = current_index
        self.queue_progress.setValue(current_index)
        self.mod_name_label.setText(f'Downloading: {mod_name} ({current_index + 1}/{self.total_mods})')
        self.prep_progress.setValue(0)
        self.download_progress.setValue(0)
        self.status_label.setText('')

    def update_prep_progress(self, percent):
        """Update the link preparation progress percentage"""
        self.prep_progress.setValue(int(percent))
        self.status_label.setText(f'Preparing: {int(percent)}%')

    def update_download_progress(self, percent):
        """Update the download progress percentage"""
        self.download_progress.setValue(int(percent))
        self.status_label.setText(f'Downloading: {int(percent)}%')


class ModInstallerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WRSR Mod Installer')
        self.setGeometry(100, 100, 1200, 700)

        # Set window icon
        logo_path = Path(__file__).parent / 'logos' / 'wrsrlogo.jfif'
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.game_folder = None
        self.target_owner_id = None
        self.mods = []
        self.scanner_thread = None
        self.downloader_thread = None
        self.download_queue = []  # Queue for multiple mod downloads
        self.total_mods_to_download = 0  # Track total for progress bar
        self.mods_downloaded_count = 0  # Track progress
        self.is_download_starting = False  # Flag to prevent multiple dialog creations

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

        # Add banner image at bottom left
        banner_path = Path(__file__).parent / 'logos' / 'wrsrbanner.png'
        if banner_path.exists():
            banner_label = QLabel()
            banner_pixmap = QPixmap(str(banner_path))
            # Scale banner to reasonable height (200px) maintaining aspect ratio
            scaled_banner = banner_pixmap.scaledToHeight(200, Qt.SmoothTransformation)
            banner_label.setPixmap(scaled_banner)
            banner_label.setAlignment(Qt.AlignCenter)
            left_layout.addWidget(banner_label)


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

            # Action button - show for mods that aren't fixed, clear for fixed ones
            if not is_fixed:
                action_btn = QPushButton('Apply Owner ID')
                action_btn.clicked.connect(lambda checked, m=mod: self.fix_mod(m))
                self.mods_table.setCellWidget(row, 5, action_btn)
            else:
                # Clear the cell widget if mod is fixed
                self.mods_table.removeCellWidget(row, 5)

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
        """Handle mod selected from catalogue (can be multiple mods)"""
        if not self.target_owner_id:
            QMessageBox.warning(self, 'Error', 'Please set a target Owner ID first')
            return

        # Add to download queue
        self.download_queue.append(mod_data)

        # Start downloading the first mod in the queue if no download is in progress
        if not self.is_download_starting and (not self.downloader_thread or not self.downloader_thread.isRunning()):
            self.is_download_starting = True
            # Create progress dialog with TOTAL queue size (wait a bit for more mods to be added)
            QTimer.singleShot(100, self._start_download_sequence)

    def _start_download_sequence(self):
        """Start the download sequence after collecting all queued mods"""
        self.is_download_starting = False

        if not self.download_queue:
            return

        # Create progress dialog with the full queue size
        self.total_mods_to_download = len(self.download_queue)
        self.mods_downloaded_count = 0
        self.download_progress_dialog = DownloadProgressDialog(self, self.total_mods_to_download)
        self.download_progress_dialog.show()

        # Start first download
        self._start_next_download()

    def _start_next_download(self):
        """Start downloading the next mod in the queue"""
        if not self.download_queue:
            return

        mod_data = self.download_queue.pop(0)
        self.mods_downloaded_count += 1

        # Start download in background thread
        self.downloader_thread = ModDownloader(
            mod_data['download_url'],
            mod_data['name'],
            self.game_folder,
            self.target_owner_id,
            mod_data.get('mod_id'),  # Pass the Steam mod ID if available
            mod_data.get('description', ''),  # Pass Skymods description
            mod_data.get('image_url')  # Pass Skymods image URL
        )
        self.downloader_thread.progress.connect(self.on_download_progress)
        self.downloader_thread.prep_progress.connect(self.on_download_prep_progress)
        self.downloader_thread.finished.connect(self.on_download_complete)
        self.downloader_thread.error.connect(self.on_download_error)
        self.downloader_thread.start()

        # Update progress dialog with current mod (reuse existing dialog)
        if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog and self.download_progress_dialog.isVisible():
            # Pass the 0-indexed current position
            self.download_progress_dialog.update_mod_name(mod_data["name"], self.mods_downloaded_count - 1)

    def on_download_prep_progress(self, mod_name, percent):
        """Update link preparation progress"""
        try:
            if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog:
                self.download_progress_dialog.update_prep_progress(percent)
        except Exception as e:
            print(f"[DEBUG] Error updating prep progress: {str(e)}")

    def on_download_progress(self, mod_name, percent):
        """Update download progress"""
        try:
            if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog:
                self.download_progress_dialog.update_download_progress(percent)
        except Exception as e:
            print(f"[DEBUG] Error updating progress: {str(e)}")

    def on_download_complete(self, mod_data):
        """Handle download completion"""
        try:
            # Refresh mods list to show new mod
            self.refresh_mods()

            # Check if there are more mods in queue
            if self.download_queue:
                # More mods to download, start the next one
                self._start_next_download()
            else:
                # All downloads complete
                if hasattr(self, 'download_progress_dialog') and self.download_progress_dialog:
                    self.download_progress_dialog.close()

                QMessageBox.information(
                    self,
                    'All Mods Downloaded',
                    f'All mods have been downloaded and installed.\n\n'
                    f'Apply the Owner ID by clicking the "Apply Owner ID" button in the mod list when ready.'
                )

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to process downloaded mod: {str(e)}')

    def on_download_error(self, error_msg):
        """Handle download error"""
        if hasattr(self, 'download_progress'):
            self.download_progress.close()
        QMessageBox.critical(self, 'Download Error', error_msg)

        # Continue with the next mod in the queue if any
        if self.download_queue:
            self._start_next_download()

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

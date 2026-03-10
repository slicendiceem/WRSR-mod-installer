import sys
import os
import json
import re
import tempfile
import py7zr
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

    def __init__(self, download_url, mod_name, game_folder, target_owner_id):
        super().__init__()
        self.download_url = download_url
        self.mod_name = mod_name
        self.game_folder = game_folder
        self.target_owner_id = target_owner_id
        self.temp_dir = None

    def run(self):
        try:
            # Create temporary directory for download
            self.temp_dir = tempfile.mkdtemp()

            # Download the file
            zip_path = Path(self.temp_dir) / f'{self.mod_name}.zip'
            self._download_file(self.download_url, zip_path)

            # Extract to workshop folder
            workshop_path = Path(self.game_folder) / 'media_soviet' / 'workshop_wip' / self.mod_name
            self._extract_mod(zip_path, workshop_path)

            # Read extracted mod config to get metadata
            mod_data = self._read_mod_config(workshop_path)
            mod_data['path'] = str(workshop_path)

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
        """Download file with progress updates"""
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

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

        except requests.exceptions.RequestException as e:
            raise Exception(f"Download failed: {str(e)}")

    def _extract_mod(self, archive_path, dest_path):
        """Extract 7z archive to destination"""
        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                # Get all items in archive
                file_list = archive.getnames()

                if not file_list:
                    raise Exception("Archive is empty")

                # Check if archive has single parent directory
                parent_dirs = set()
                for item in file_list:
                    parts = item.split('/')
                    if len(parts) > 1:
                        parent_dirs.add(parts[0])

                # If all items start with single directory, extract contents up one level
                if len(parent_dirs) == 1:
                    parent = list(parent_dirs)[0]
                    # Extract all and strip parent directory
                    dest_path.mkdir(parents=True, exist_ok=True)
                    archive.extractall(path=dest_path)

                    # Move files from parent subdir to dest_path
                    parent_path = dest_path / parent
                    if parent_path.exists():
                        for item in parent_path.iterdir():
                            item.rename(dest_path / item.name)
                        parent_path.rmdir()
                else:
                    # Extract directly
                    dest_path.mkdir(parents=True, exist_ok=True)
                    archive.extractall(path=dest_path)

        except py7zr.Bad7zFile:
            raise Exception("Invalid 7z archive format")
        except Exception as e:
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


class ModCatalogueDialog(QDialog):
    """Dialog for searching and downloading mods from Skymods"""
    mod_selected = pyqtSignal(dict)  # Emits mod data with download_url

    SKYMODS_BASE_URL = 'https://catalogue.smods.ru'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Search and Download Mods from Skymods')
        self.setGeometry(100, 100, 1100, 700)
        self.search_results = []
        self.selected_mod = None

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
        """Search Skymods for mods matching the search term"""
        search_term = self.search_input.text().strip()
        if not search_term:
            self.results_label.setText('Please enter a search term')
            return

        self.results_label.setText(f'Searching for "{search_term}"...')
        self.results_list.clear()
        self.selected_mod = None
        self.details_label.setText('Searching...')

        try:
            self.search_results = self._fetch_all_results(search_term)

            if self.search_results:
                self.results_label.setText(f'Found {len(self.search_results)} mod(s)')
                self._populate_results_list()
            else:
                self.results_label.setText(f'No mods found for "{search_term}"')
                self.details_label.setText('Try a different search term')

        except Exception as e:
            self.results_label.setText('Error searching Skymods')
            self.details_label.setText(f'Error: {str(e)}')

    def _fetch_all_results(self, search_term):
        """Fetch ALL search results from Skymods (all pages)"""
        all_mods = []
        page = 1
        max_pages = 50  # Safety limit

        while page <= max_pages:
            try:
                url = f'{self.SKYMODS_BASE_URL}/?s={search_term}&paged={page}'
                response = requests.get(url, timeout=30)  # Increased timeout for Skymods
                response.raise_for_status()

                mods_on_page = self._parse_results_page(response.text, search_term)

                if not mods_on_page:
                    break  # No more results

                all_mods.extend(mods_on_page)
                page += 1

            except Exception as e:
                if page == 1:
                    raise  # Error on first page is critical
                break  # Stop pagination on later pages

        return all_mods

    def _parse_results_page(self, html, search_term):
        """Parse a single Skymods search results page"""
        mods = []
        try:
            import re

            # Look for mod entries - search for title and download link patterns
            # Pattern: Find mod titles and associate with download links
            mod_pattern = r'<a[^>]*href="([^"]*)"[^>]*>\s*([^<]+(?:' + re.escape(search_term) + r'[^<]*)?)<\s*/a>'

            # More specific: look for post titles
            post_pattern = r'<h[2-3][^>]*class="[^"]*post-title[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a'
            matches = re.finditer(post_pattern, html, re.IGNORECASE | re.DOTALL)

            for match in matches:
                mod_url = match.group(1)
                mod_name = match.group(2).strip()

                if mod_url and mod_name:
                    # Extract download link from mod page
                    download_url = self._extract_download_link(mod_url)

                    if download_url:
                        mods.append({
                            'name': mod_name[:100],  # Limit name length
                            'url': mod_url,
                            'download_url': download_url,
                        })

            # If no results with above pattern, try simpler approach
            if not mods:
                # Look for any links that might be mods
                link_pattern = r'<a[^>]*href="' + re.escape(self.SKYMODS_BASE_URL) + r'/([^/"]+)[^"]*"[^>]*>([^<]{5,100})</a>'
                matches = re.finditer(link_pattern, html)

                for match in matches:
                    mod_slug = match.group(1)
                    mod_name = match.group(2).strip()

                    if search_term.lower() in mod_name.lower():
                        mod_url = f'{self.SKYMODS_BASE_URL}/{mod_slug}'
                        download_url = self._extract_download_link(mod_url)

                        if download_url:
                            mods.append({
                                'name': mod_name,
                                'url': mod_url,
                                'download_url': download_url,
                            })

        except Exception as e:
            pass

        return mods

    def _extract_download_link(self, mod_page_url):
        """Extract the 7z download link from a mod page"""
        try:
            response = requests.get(mod_page_url, timeout=20)  # Increased timeout for Skymods
            response.raise_for_status()

            import re
            # Look for 7z download links
            patterns = [
                r'href="([^"]*\.7z[^"]*)"',
                r'href="(https://[^"]*?\.7z?[^"]*)"',
                r'<a[^>]*href="([^"]*)"[^>]*>.*?Download.*?</a>',
            ]

            for pattern in patterns:
                match = re.search(pattern, response.text, re.IGNORECASE)
                if match:
                    link = match.group(1)
                    if '://' not in link:
                        link = self.SKYMODS_BASE_URL + link
                    return link

        except Exception as e:
            pass

        return None

    def _populate_results_list(self):
        """Populate the results list widget"""
        self.results_list.clear()
        for mod in self.search_results:
            status = "✓ Download available" if mod['download_url'] else "⚠ No download"
            display_name = f"{mod['name']} [{status}]"
            item = self.results_list.addItem(display_name)

    def on_result_selected(self, item):
        """Show mod details when selected"""
        row = self.results_list.row(item)
        if 0 <= row < len(self.search_results):
            self.selected_mod = self.search_results[row]

            details = (
                f"<b>{self.selected_mod['name']}</b><br><br>"
                f"<a href='{self.selected_mod['url']}'>View on Skymods</a><br><br>"
            )

            if self.selected_mod['download_url']:
                details += "✓ Download link available<br>Click 'Download Selected' to proceed."
            else:
                details += "⚠ No 7z download found<br><a href='" + self.selected_mod[
                    'url'] + "'>Visit page to download manually</a>"

            self.details_label.setText(details)

    def on_download_clicked(self):
        """Emit signal when user clicks download"""
        if not self.selected_mod:
            QMessageBox.warning(self, 'Error', 'Please select a mod from results')
            return

        if not self.selected_mod['download_url']:
            QMessageBox.warning(
                self, 'No Download',
                'This mod does not have a direct 7z download link.\n\n'
                'Please download it manually from the Skymods page.'
            )
            return

        self.mod_selected.emit(self.selected_mod)
        self.close()


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

        dialog = ModCatalogueDialog(self)
        dialog.mod_selected.connect(self.on_mod_selected_from_catalogue)
        dialog.exec_()

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
            self.target_owner_id
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

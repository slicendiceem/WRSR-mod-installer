"""Start the WRSR Mod Installer.

The app lives in the wrsr_installer package; this file keeps `python mod_installer.py`,
run.bat and the PyInstaller build working as before.
"""

from wrsr_installer.app import main

if __name__ == '__main__':
    main()

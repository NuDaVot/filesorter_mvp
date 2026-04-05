# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for FileSorter MVP.
# Usage:
#   pyinstaller build/FileSorter.spec
#
# Notes:
# - This spec builds a one-folder bundle by default. For one-file use the CLI flags (--onefile).
# - For MVP, config.json is expected to be placed next to the .exe at runtime (external file).

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = collect_submodules('PySide6')

a = Analysis(
    ['filesorter/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # ('config.json', '.'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FileSorter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)

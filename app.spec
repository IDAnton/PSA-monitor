# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_submodules

# -----------------------------
# Сбор всех подмодулей PyOpenGL
hidden_imports = collect_submodules('OpenGL') + ['PyQt5.QtOpenGL']

# -----------------------------
# Анализ
a = Analysis(
    ['app.py'],               # твой главный скрипт
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=['pyopengl_hook.py'],  # runtime hook для PyOpenGL
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # False если окно GUI, True если нужно консольное окно
)
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for hledger-textual Windows bundle."""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect Textual's bundled CSS/assets and plotext data files
textual_datas = collect_data_files("textual")
plotext_datas = collect_data_files("textual_plotext")
babel_datas = collect_data_files("babel")

a = Analysis(
    ["src/hledger_textual/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        # App stylesheet
        ("src/hledger_textual/styles/app.tcss", "hledger_textual/styles"),
        # Textual, plotext, and babel bundled data
        *textual_datas,
        *plotext_datas,
        *babel_datas,
    ],
    hiddenimports=[
        # Textual internals loaded dynamically
        *collect_submodules("textual"),
        *collect_submodules("textual_plotext"),
        # Babel locale data
        *collect_submodules("babel"),
        # fpdf2
        "fpdf",
        "fpdf.fonts",
        # pricehist (optional — only used when live prices are fetched)
        "pricehist",
        # TOML support for Python < 3.11
        "tomli",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle lean — test frameworks are never needed at runtime
        "pytest",
        "pytest_asyncio",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hledger-textual",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Terminal app — must keep console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="hledger-textual",
)

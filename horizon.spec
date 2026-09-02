# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour Horizon (build Windows, mode --onedir).

    pyinstaller --noconfirm horizon.spec   ->   dist/Horizon/Horizon.exe

Mode onedir et non onefile : l'application charge ses ressources dans un
QWebEngineView via des URLs file://, et onefile les re-extrait dans un dossier
temporaire a chaque lancement (demarrage lent et fragile avec QtWebEngine).

Les modules resolvent leurs ressources avec Path(__file__).parent, qui pointe
vers dist/Horizon/_internal/horizon dans l'application gelee : les `datas`
ci-dessous reproduisent donc a l'identique l'arborescence du package.
"""

from pathlib import Path

ROOT = Path(SPECPATH)
PKG = ROOT / "src" / "horizon"

# Genere par tools/make_icon.py ; absent -> executable sans icone.
_ico = ROOT / "build" / "horizon.ico"
icon = str(_ico) if _ico.exists() else None

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        # widgets/markdown.py, widgets/webeditor.py, widgets/project.py,
        # dialogs.py, theme.py
        (str(PKG / "resources"), "horizon/resources"),
        # theme.py : load() lit themes/terminal.json sans garde
        (str(PKG / "themes"), "horizon/themes"),
        # preferences.py
        (str(PKG / "preferences.json"), "horizon"),
    ],
    hiddenimports=[
        # importe pour son effet de bord (enregistrement des ressources Qt)
        "horizon.resources_rc",
        # importes dans un try/except (widgets/calendar.py) : PyInstaller ne les
        # verrait pas et l'integration Outlook casserait silencieusement
        "win32com.client",
        "pythoncom",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Ne pas exclure de modules Qt : QtWebEngine tire QtQuick, QtNetwork,
    # QtPositioning et QtWebChannel.
    excludes=["tkinter", "pydoc_data"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Horizon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Horizon",
)

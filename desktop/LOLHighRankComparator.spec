# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "desktop" / "lol_high_rank_comparator.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "desktop" / "all-champion-baselines.json"), "desktop"),
        (str(root / "desktop" / "bootstrap-replays.json"), "desktop"),
        (str(root / "assets" / "player-case.js"), "assets"),
        (str(root / "assets" / "map11.png"), "assets"),
        (str(root / "assets" / "item-data.json"), "assets"),
        (str(root / "assets" / "summoner-spells.json"), "assets"),
        (str(root / "assets" / "ddragon"), "assets/ddragon"),
        (str(root / "config" / "model-parameters.json"), "config"),
    ],
    hiddenimports=["tkinter", "tkinter.ttk", "tkinter.messagebox"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LOLHighRankComparator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

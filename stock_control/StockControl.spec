# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('productos.xlsx', '.'), ('static', 'static'), ('templates', 'templates'), ('venv\\Lib\\site-packages\\escpos\\*.json', 'escpos'), ('seed_db.sqlite3', '.')],
    hiddenimports=['django', 'escpos', 'escpos.printer', 'escpos.escpos', 'escpos.capabilities', 'escpos.printer.win32', 'usb.core', 'usb.util', 'serial'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StockControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StockControl',
)

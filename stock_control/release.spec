# -*- mode: python ; coding: utf-8 -*-
# Single-file release build — produces dist/StockControl.exe
#
# Uso:
#   pyinstaller release.spec --clean
#
# La sección datas usa collect_data_files('escpos') en lugar del path
# hardcodeado 'venv\\Lib\\site-packages\\escpos\\*.json' para que el
# spec funcione en cualquier entorno (CI, entornos virtuales con nombre
# distinto a 'venv', instalaciones globales de Python).

from PyInstaller.utils.hooks import collect_data_files

escpos_datas = collect_data_files('escpos')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('productos.xlsx', '.'),
        ('static', 'static'),
        ('templates', 'templates'),
        ('seed_db.sqlite3', '.'),
        ('version.py', '.'),
        # Management commands: Django los descubre escaneando el filesystem;
        # en un exe single-file deben incluirse como datas para que PyInstaller
        # los extraiga al directorio temporal y pkgutil.iter_modules() los encuentre.
        ('app_inventario/management', 'app_inventario/management'),
        *escpos_datas,
    ],
    hiddenimports=[
        'django', 'escpos', 'escpos.printer', 'escpos.escpos',
        'escpos.capabilities', 'escpos.printer.win32',
        'usb.core', 'usb.util', 'serial',
        # Management commands de app_inventario
        'app_inventario.management',
        'app_inventario.management.commands',
        'app_inventario.management.commands.cargar_productos',
        'app_inventario.management.commands.send_daily_report',
        'app_inventario.management.commands.reactivar_balde',
    ],
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
    a.binaries,
    a.datas,
    [],
    name='StockControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

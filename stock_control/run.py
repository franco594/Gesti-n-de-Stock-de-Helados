# run.py
import os
import sys
from pathlib import Path
import threading
import time
import webbrowser

import django

def _default_db_path() -> Path:
    root = Path(os.getenv("LOCALAPPDATA", str(Path(__file__).resolve().parent)))
    return root / "StockControl" / "db.sqlite3"

def _ensure_db_seed():
    base_dir = Path(__file__).resolve().parent
    db_file = _default_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    seed = base_dir / "seed_db.sqlite3"
    if not db_file.exists() and seed.exists():
        import shutil
        shutil.copy2(seed, db_file)

_ensure_db_seed()

def main():
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock_control.settings")
    django.setup()  # Asegura settings cargados

    # --- BACKUP AL ARRANCAR (sólo proceso padre, no reloader) ---
    if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
        try:
            from app_inventario.utils.backups import make_startup_backup
            path_bkp = make_startup_backup(keep_last=15)
            if path_bkp:
                print(f"💾 Backup inicial creado: {path_bkp}")
        except Exception as e:
            print(f"⚠️ No se pudo crear el backup inicial: {e}")

        # Iniciar lector de códigos en background (una sola vez)
        try:
            import lector_codigos
            threading.Thread(target=lector_codigos.iniciar_lector, daemon=True).start()
            print("🔍 Escáner activo. Escanea un código en cualquier ventana...")
        except Exception as e:
            print(f"⚠️ No se pudo iniciar el lector de códigos: {e}")

        # Abrir navegador una sola vez
        def _abrir():
            time.sleep(1)
            webbrowser.open("http://127.0.0.1:8000")
        threading.Thread(target=_abrir, daemon=True).start()

    # Si es exe y no hay args -> arrancar server por defecto, SIN reloader
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        sys.argv += ["runserver", "127.0.0.1:8000", "--noreload"]

    # Si pidieron runserver pero se olvidaron --noreload, lo agregamos
    if "runserver" in sys.argv and "--noreload" not in sys.argv:
        sys.argv.append("--noreload")

    try:
        from django.core.management import execute_from_command_line
        execute_from_command_line(sys.argv)
    except Exception as e:
        print("\n❌ Error al ejecutar la app:", e)
        if getattr(sys, "frozen", False):
            input("\nPresioná Enter para salir...")


if __name__ == "__main__":
    webbrowser.open("http://127.0.0.1:8000")  # Cambia la URL si usas otro puerto
    main()

# run.py
import os
import sys
from pathlib import Path
import webbrowser

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
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock_control.settings")

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

import glob
import os
import sqlite3

from django.conf import settings
from django.utils import timezone


def _get_backups_dir() -> str:
    """
    Devuelve el directorio de backups persistente.

    PyInstaller extrae los archivos del exe a un directorio temporal que se
    borra al cerrar la aplicación. Por eso no se usa settings.BASE_DIR sino
    %LOCALAPPDATA%/StockControl/backups, que persiste entre ejecuciones.

    En desarrollo (sin PyInstaller) cae en un directorio 'backups' junto al
    proyecto para facilitar la inspección manual.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, "StockControl", "backups")
    # Fallback para desarrollo / entornos sin LOCALAPPDATA (Linux/Mac CI)
    return os.path.join(settings.BASE_DIR, "backups")


def make_startup_backup(keep_last: int = 15) -> str | None:
    """
    Crea una copia segura de la DB actual usando la SQLite Online Backup API.

    Ventajas respecto a shutil.copy2:
    - La API de backup de SQLite es segura con la DB abierta (no requiere
      detener Django ni hacer flush de WAL manualmente).
    - El archivo de destino queda en %LOCALAPPDATA%/StockControl/backups,
      fuera del directorio temporal de PyInstaller.

    Mantiene los últimos `keep_last` backups (rotación FIFO).
    Retorna la ruta del backup creado, o None si la DB no existe.
    """
    db_path = settings.DATABASES["default"]["NAME"]
    if not os.path.exists(db_path):
        return None

    backups_dir = _get_backups_dir()
    os.makedirs(backups_dir, exist_ok=True)

    ts = timezone.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(backups_dir, f"db-{ts}.sqlite3")

    # SQLite Online Backup API: copia segura mientras la DB está abierta
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Rotación: eliminar backups más antiguos
    files = sorted(glob.glob(os.path.join(backups_dir, "db-*.sqlite3")))
    if len(files) > keep_last:
        for old in files[: len(files) - keep_last]:
            try:
                os.remove(old)
            except Exception:
                pass

    return out

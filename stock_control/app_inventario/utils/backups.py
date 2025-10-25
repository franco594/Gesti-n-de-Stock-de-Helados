import os, glob, shutil
from django.conf import settings
from django.utils import timezone

def make_startup_backup(keep_last: int = 15) -> str | None:
    """
    Copia la DB actual a /backups/db-YYYYMMDD-HHMMSS.sqlite3.
    Mantiene sólo los últimos `keep_last` backups.
    """
    db_path = settings.DATABASES["default"]["NAME"]
    if not os.path.exists(db_path):
        return None

    backups_dir = os.path.join(settings.BASE_DIR, "backups")
    os.makedirs(backups_dir, exist_ok=True)

    ts = timezone.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(backups_dir, f"db-{ts}.sqlite3")
    shutil.copy2(db_path, out)

    # Rotación: borro antiguos
    files = sorted(glob.glob(os.path.join(backups_dir, "db-*.sqlite3")))
    if len(files) > keep_last:
        for old in files[: len(files) - keep_last]:
            try:
                os.remove(old)
            except Exception:
                pass

    return out

import os
from django.apps import AppConfig

class AppInventarioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_inventario"

    def ready(self):
        # ...
        from django.db import connection
        try:
            with connection.cursor() as c:
                c.execute("PRAGMA table_info(app_inventario_stockbalde);")
                cols = [r[1] for r in c.fetchall()]
                if "is_activo" not in cols:
                    c.execute("ALTER TABLE app_inventario_stockbalde ADD COLUMN is_activo INTEGER NOT NULL DEFAULT 1;")
                    c.execute("CREATE INDEX IF NOT EXISTS stockbalde_is_activo_idx ON app_inventario_stockbalde(is_activo);")
        except Exception:
            # No romper el arranque si la DB aún no existe (migraciones iniciales)
            pass


class AppInventarioConfig(AppConfig):
    name = "app_inventario"

    def ready(self):
        from . import signals  # noqa: F401  (importa y registra)

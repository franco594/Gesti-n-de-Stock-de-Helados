import os
import sys
from django.apps import AppConfig

class AppInventarioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_inventario"

    def ready(self):
        # 1) Patch/índice para SQLite si falta la columna is_activo
        from django.db import connection
        try:
            with connection.cursor() as c:
                c.execute("PRAGMA table_info(app_inventario_stockbalde);")
                cols = [r[1] for r in c.fetchall()]
                if "is_activo" not in cols:
                    c.execute("""
                        ALTER TABLE app_inventario_stockbalde
                        ADD COLUMN is_activo INTEGER NOT NULL DEFAULT 1;
                    """)
                    c.execute("""
                        CREATE INDEX IF NOT EXISTS stockbalde_is_activo_idx
                        ON app_inventario_stockbalde(is_activo);
                    """)
        except Exception:
            # No romper el arranque si la DB aún no existe (migraciones iniciales)
            pass

        # 2) Registrar señales
        try:
            from . import signals  # noqa: F401
        except Exception:
            # No bloquear el arranque si aún no existen
            pass

        # 3) Iniciar scheduler SOLO en servidor web y evitando doble arranque
        # cmds_admitidos = ("runserver", "gunicorn", "uwsgi")
        # if not any(cmd in " ".join(sys.argv) for cmd in cmds_admitidos):
        #     return

        # Evitar doble start con el autoreloader (Django/ Werkzeug)
        # if os.environ.get("RUN_MAIN") != "true" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        #   return

        #try:
        #    from app_inventario.utils.scheduler import iniciar_tareas_periodicas
        #    iniciar_tareas_periodicas()
        #except Exception as e:
        #    print(f"⚠️ No se pudo iniciar el scheduler: {e}")

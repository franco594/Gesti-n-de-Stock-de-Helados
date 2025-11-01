import os
import sys
import threading
from django.apps import AppConfig

_scheduler_started = False
_scheduler_lock = threading.Lock()

class AppInventarioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_inventario"

    def ready(self):
        # 1) Patch/índice SQLite si falta la columna is_activo
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
            pass  # la DB aún no está creada (migraciones iniciales)

        # 2) Registrar señales (si existen)
        try:
            from . import signals  # noqa
        except Exception:
            pass

        # 3) Iniciar scheduler solo una vez (evita doble start en runserver o PyInstaller)
        global _scheduler_started
        with _scheduler_lock:
            if _scheduler_started:
                return

            # Evitar duplicación por autoreloader
            if os.environ.get("RUN_MAIN") == "true":  # Django
                pass
            elif "gunicorn" in " ".join(sys.argv):
                pass
            else:
                # Ejecutando EXE → continuar normal
                pass

            try:
                from app_inventario.utils.scheduler import iniciar_tareas_periodicas
                iniciar_tareas_periodicas()
                print("✅ Scheduler diario inicializado (23:59).")
                _scheduler_started = True
            except Exception as e:
                print(f"⚠️ No se pudo iniciar el scheduler: {e}")

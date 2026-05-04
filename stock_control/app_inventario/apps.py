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
        # ✅ Solo ejecutar si Django está completamente inicializado
        # y no estamos en migraciones
        if self._es_comando_migracion():
            return
        
        # 1) Patch/índice SQLite si falta la columna is_activo
        # ✅ Ejecutar en thread separado para no bloquear el inicio
        def _patch_db():
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
                        print("✅ Columna is_activo agregada")
            except Exception:
                pass  # la DB aún no está creada (migraciones iniciales)
        
        # ✅ Ejecutar el patch en background después de un delay
        threading.Timer(2.0, _patch_db).start()

        # 2) Registrar señales (si existen)
        try:
            from . import signals  # noqa
        except Exception:
            pass

        # 3) Iniciar scheduler solo una vez
        global _scheduler_started
        with _scheduler_lock:
            if _scheduler_started:
                return

            # ✅ Solo iniciar en proceso principal
            if not self._es_proceso_principal():
                return

            # ✅ Iniciar scheduler en background después de un delay
            def _iniciar_scheduler_delayed():
                try:
                    from app_inventario.utils.scheduler import iniciar_tareas_periodicas
                    iniciar_tareas_periodicas()
                    print("✅ Scheduler diario inicializado (23:59).")
                except Exception as e:
                    print(f"⚠️ No se pudo iniciar el scheduler: {e}")
            
            threading.Timer(3.0, _iniciar_scheduler_delayed).start()
            _scheduler_started = True

    def _es_comando_migracion(self):
        """Detectar si estamos ejecutando migrate/makemigrations"""
        return any(cmd in sys.argv for cmd in ['migrate', 'makemigrations', 'showmigrations'])
    
    def _es_proceso_principal(self):
        """
        Detectar si estamos en el proceso principal.
        - En desarrollo con autoreload: RUN_MAIN != "true"
        - En producción/exe: RUN_MAIN es None
        """
        run_main = os.environ.get("RUN_MAIN")
        es_exe = getattr(sys, 'frozen', False)
        
        # Si es exe, siempre es proceso principal
        if es_exe:
            return True
        
        # Si es desarrollo, solo el proceso padre (RUN_MAIN != "true")
        return run_main != "true"
# run.py - VERSIÓN CORREGIDA
import os
import sys
from pathlib import Path
import threading
import time
import webbrowser

def _corregir_baldes_incorrectamente_activos():
    """
    Detecta y corrige baldes que quedaron marcados como is_activo=True
    cuando deberían estar inactivos, causado por el bug en eliminar_movimiento /
    eliminar_item_movimiento que usaba bulk .update(is_activo=True) filtrando
    solo por codigo_barras (reactivaba baldes de otros retiros con barcode duplicado).

    Lógica: para cada codigo_barras en retiros registrados, si hay más retiros
    activos que baldes inactivos con ese código, los baldes activos sobrantes
    (los más viejos, por FIFO) deberían estar inactivos.
    """
    from collections import defaultdict
    from django.utils import timezone

    # Importar modelos después de django.setup()
    from app_inventario.models import StockBalde, RegistroMovimiento

    retiros_por_codigo = defaultdict(int)
    for cb in (
        RegistroMovimiento.objects
        .filter(tipo="salida")
        .exclude(codigo_barras="")
        .exclude(codigo_barras__isnull=True)
        .values_list("codigo_barras", flat=True)
    ):
        retiros_por_codigo[cb] += 1

    inactivos_por_codigo = defaultdict(int)
    for cb in (
        StockBalde.objects
        .filter(is_activo=False)
        .exclude(codigo_barras="")
        .values_list("codigo_barras", flat=True)
    ):
        inactivos_por_codigo[cb] += 1

    corregidos = 0
    for cb, n_retiros in retiros_por_codigo.items():
        n_inactivos = inactivos_por_codigo[cb]
        exceso = n_retiros - n_inactivos
        if exceso <= 0:
            continue

        # Marcar los más viejos como inactivos (FIFO: los más viejos debieron
        # haberse retirado primero, por eso son los incorrectamente activos)
        baldes_a_corregir = list(
            StockBalde.objects
            .filter(codigo_barras=cb, is_activo=True)
            .order_by("timestamp", "id")[:exceso]
        )
        for b in baldes_a_corregir:
            b.is_activo = False
            b.fecha_retiro = timezone.now()
            b.save(update_fields=["is_activo", "fecha_retiro"])
            corregidos += 1

    if corregidos:
        print(f"🔧 Stock corregido: {corregidos} balde(s) inactivos incorrectamente marcados como activos fueron saneados.")


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
    django.setup()

    # --- FLAGS INICIALES ---
    es_proceso_principal = os.environ.get("RUN_MAIN") != "true"
    es_exe = getattr(sys, "frozen", False)
    
    # --- CONFIGURACIÓN DE ARGUMENTOS (PRIMERO) ---
    if es_exe and len(sys.argv) == 1:
        sys.argv += ["runserver", "127.0.0.1:8000", "--noreload"]
    
    # ✅ VERIFICAR DESPUÉS DE AGREGAR ARGUMENTOS
    es_runserver = "runserver" in sys.argv
    
    if es_exe and es_runserver and "--noreload" not in sys.argv:
        sys.argv.append("--noreload")
    
    # --- INICIAR COMPONENTES ---
    if es_runserver and es_proceso_principal:
        # --- BACKUP ---
        try:
            from app_inventario.utils.backups import make_startup_backup
            path_bkp = make_startup_backup(keep_last=15)
            if path_bkp:
                print(f"💾 Backup inicial creado: {path_bkp}")
        except Exception as e:
            print(f"⚠️ No se pudo crear el backup inicial: {e}")

        # --- LECTOR DE CÓDIGOS ---
        try:
            import lector_codigos
            threading.Thread(target=lector_codigos.iniciar_lector, daemon=True).start()
            print("🔍 Escáner activo. Escanea un código en cualquier ventana...")
        except Exception as e:
            print(f"⚠️ No se pudo iniciar el lector de códigos: {e}")

        # --- ABRIR NAVEGADOR ---
        def _abrir_cuando_este_listo():
            import socket
            
            url = "http://127.0.0.1:8000"
            max_intentos = 90
            
            print("⏳ Esperando que el servidor inicie...")
            
            for i in range(max_intentos):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    resultado = sock.connect_ex(("127.0.0.1", 8000))
                    sock.close()
                    
                    if resultado == 0:
                        time.sleep(1)
                        print("🌐 Abriendo navegador...")
                        webbrowser.open(url)
                        return
                    
                except Exception:
                    pass
                
                time.sleep(1)
            
            print(f"⚠️ No se pudo abrir automáticamente. Abrí: {url}")
        
        threading.Thread(target=_abrir_cuando_este_listo, daemon=True).start()

    # --- MIGRACIONES ---
    if es_runserver and es_proceso_principal:
        try:
            from django.core.management import call_command
            call_command("migrate", "--run-syncdb", verbosity=0)
            print("✅ Migraciones aplicadas")
        except Exception as e:
            print(f"⚠️ Error al aplicar migraciones: {e}")

    # --- CORRECCIÓN DE STOCK CORRUPTO (one-time fix por bug de anulación de retiros) ---
    # El bug: eliminar_movimiento/eliminar_item_movimiento hacía bulk .update(is_activo=True)
    # filtrando solo por codigo_barras. Con barcodes duplicados (mismo PLU+peso = mismo EAN-13)
    # esto reactivaba baldes de OTROS retiros que no tenían nada que ver, dejando baldes
    # viejos como activos cuando deberían estar inactivos.
    # Esta rutina detecta y corrige cualquier balde que esté incorrectamente activo.
    if es_runserver and es_proceso_principal:
        try:
            _corregir_baldes_incorrectamente_activos()
        except Exception as e:
            print(f"⚠️ Error en corrección de stock: {e}")

    # --- EJECUTAR DJANGO ---
    try:
        from django.core.management import execute_from_command_line
        execute_from_command_line(sys.argv)
    except Exception as e:
        print("\n❌ Error al ejecutar la app:", e)
        if es_exe:
            input("\nPresioná Enter para salir...")


if __name__ == "__main__":
    main()
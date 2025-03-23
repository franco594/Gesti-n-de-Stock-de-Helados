# app_inventario/jobs.py
import os
import subprocess
from datetime import datetime

def backup_postgresql():
    from django.conf import settings

    # Nombre del archivo de backup
    fecha = datetime.now().strftime("%Y-%m-%d_%H-%M")
    nombre_archivo = f"backup_{fecha}.sql"

    # Ruta del backup
    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    ruta_completa = os.path.join(backup_dir, nombre_archivo)

    # Configuración de PostgreSQL (ajustar según tus credenciales)
    db_name = settings.DATABASES['default']['NAME']
    db_user = settings.DATABASES['default']['USER']
    db_password = settings.DATABASES['default']['PASSWORD']
    db_host = settings.DATABASES['default'].get('HOST', 'localhost')
    db_port = settings.DATABASES['default'].get('PORT', '5432')

    os.environ['PGPASSWORD'] = db_password

    try:
        comando = [
            'pg_dump',
            '-h', db_host,
            '-p', db_port,
            '-U', db_user,
            '-F', 'c',
            '-b',
            '-v',
            '-f', ruta_completa,
            db_name
        ]
        subprocess.run(comando, check=True)
        print(f"✅ Backup realizado con éxito: {ruta_completa}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error al realizar el backup: {e}")
    finally:
        del os.environ['PGPASSWORD']

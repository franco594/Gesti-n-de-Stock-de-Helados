import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- DEFAULT_AUTO_FIELD recomendado (evita warnings y usa bigint) ---
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

def _default_db_path() -> Path:
    """
    Ruta por defecto persistente para la DB:
    - En Windows: %LOCALAPPDATA%\\StockControl\\db.sqlite3
    - Fallback (si no existe LOCALAPPDATA): BASE_DIR/StockControl/db.sqlite3
    Podés sobreescribir con la variable de entorno DB_FILE.
    """
    root = Path(os.getenv("LOCALAPPDATA", str(BASE_DIR)))
    return root / "StockControl" / "db.sqlite3"

DB_FILE = Path(os.getenv("DB_FILE", _default_db_path()))
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-key-cambiar-en-produccion-00000000000000")

DEBUG = True

ALLOWED_HOSTS = ['*']

TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_TZ = True

# ✅ Asegurate de no sobreescribir INSTALLED_APPS al final del archivo
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app_inventario',
    'compressor',  # Añadido correctamente acá
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    #'compression_middleware.middleware.CompressionMiddleware',
]

ROOT_URLCONF = 'stock_control.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'stock_control.wsgi.application'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DB_FILE),   # ¡IMPORTANTE!: ruta absoluta persistente
    }
}

# Archivos estáticos
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# django-compressor
COMPRESS_ROOT = STATIC_ROOT

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
]

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'stock_control_cache',
    }
}

EPSON_BACKEND = os.getenv("EPSON_BACKEND", "spooler")
EPSON_PRINTER_NAME = os.getenv("EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt")
NOMBRE_COMERCIO = os.getenv("NOMBRE_COMERCIO", "Gestión de Stock")
PRINT_COPIAS = int(os.getenv("PRINT_COPIAS", "1"))
PRINT_LOGO_PATH = os.getenv("PRINT_LOGO_PATH", "")
PRINT_QR = os.getenv("PRINT_QR", "false").lower() == "true"

PRINT_FROM_VIEWS = True

# Auto-updater
GITHUB_REPO       = "franco594/Gesti-n-de-Stock-de-Helados"
UPDATE_ASSET_NAME = "StockControl.exe"


LEGACY_ALLOW_NO_CODE = False

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "francopiero594@gmail.com"
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_TZ = True

# ────────────────────────────────────────────────────────────────────────────
# CLOUD BACKUPS
# ────────────────────────────────────────────────────────────────────────────

CLOUD_BACKUP_PROVIDER = 'google_drive'  # 'google_drive', 'dropbox', 'onedrive'
CLOUD_BACKUP_KEEP = 30                   # Mantener las últimas 30 copias
CLOUD_BACKUP_DELETE_LOCAL = True         # Borrar archivo local después de subir
CLOUD_BACKUP_AUTO_DAILY = True           # Backup automático diario
CLOUD_BACKUP_AUTO_ON_MOVEMENT = False    # Backup cada ingreso/retiro (puede ser excesivo)

# ─── Google Drive ───────────────────────────────────────────────────────────
GOOGLE_DRIVE_CREDENTIALS_FILE = 'credentials.json'      # Del Google Cloud Console
GOOGLE_DRIVE_TOKEN_FILE = 'token.json'                  # Se crea automáticamente
GOOGLE_DRIVE_FOLDER_NAME = 'StockControl Backups'       # Carpeta en Google Drive

# ─── Dropbox ────────────────────────────────────────────────────────────────
DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_TOKEN', '')   # Token de la app de Dropbox
DROPBOX_FOLDER = '/StockControl Backups'                # Carpeta en Dropbox

# ─── OneDrive ───────────────────────────────────────────────────────────────
ONEDRIVE_CLIENT_ID = os.getenv('ONEDRIVE_CLIENT_ID', '')
ONEDRIVE_CLIENT_SECRET = os.getenv('ONEDRIVE_CLIENT_SECRET', '')
ONEDRIVE_FOLDER = 'StockControl Backups'
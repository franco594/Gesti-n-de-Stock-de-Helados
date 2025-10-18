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

SECRET_KEY = 'tu_clave_secreta'

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
PRINT_COPIAS = 1  # o las copias que quieras
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

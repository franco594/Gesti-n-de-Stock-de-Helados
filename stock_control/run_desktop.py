import webview
import threading
import os
import sys
import django

# Establecer configuración de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_control.settings')
django.setup()

# Iniciar el servidor Django en segundo plano
def run_server():
    os.system("python manage.py runserver 127.0.0.1:8000")

if __name__ == '__main__':
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    # Abrir pywebview apuntando al servidor local
    webview.create_window('Gestión de Stock', 'http://127.0.0.1:8000', width=1200, height=800)
    webview.start()

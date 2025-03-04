import os
import sys
import threading
import lector_codigos  # Importa el lector de códigos
from django.core.management import execute_from_command_line


def iniciar_lector_en_hilo():
    """Inicia el lector de códigos en un hilo separado para que no bloquee Django."""
    hilo_lector = threading.Thread(target=lector_codigos.iniciar_lector, daemon=True)
    hilo_lector.start()

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_control.settings')
    try:
        execute_from_command_line(sys.argv)
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. ¿Está instalado y disponible en tu entorno?"
        ) from exc

if __name__ == '__main__':
    iniciar_lector_en_hilo()  # Inicia el lector de códigos antes de arrancar Django
    main()

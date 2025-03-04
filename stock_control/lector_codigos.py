import requests
import keyboard
import time
import threading

URL = "http://127.0.0.1:8000/api/procesar_codigo/"  # Asegúrate de usar el puerto correcto de Django
codigo_actual = ""

def enviar_codigo():
    """Envía el código escaneado al servidor Django."""
    global codigo_actual
    if codigo_actual:
        print(f"📡 Enviando código: {codigo_actual}")
        try:
            response = requests.post(URL, json={"codigo": codigo_actual})
            data = response.json()
            print(f"✅ Respuesta del servidor: {data}")
        except requests.exceptions.RequestException as e:
            print(f"🚨 Error de conexión: {e}")

        codigo_actual = ""  # Reset para el siguiente código

def capturar_tecla(event):
    """Captura teclas presionadas y forma el código de barras."""
    global codigo_actual
    if event.name == "enter":  # Si el escáner envía ENTER al final del código
        enviar_codigo()
    elif len(event.name) == 1:  # Evita teclas especiales como shift, ctrl, alt
        codigo_actual += event.name

def iniciar_lector():
    """Inicia el lector de códigos de barras en un hilo separado."""
    print("🔍 Escáner activo. Escanea un código en cualquier ventana...")

    # Iniciar escucha de teclado en un bucle infinito
    keyboard.on_press(capturar_tecla)

    # Mantener el hilo en ejecución para capturar teclas
    while True:
        time.sleep(1)

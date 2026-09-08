# lector_codigos.py
#
# NOTA: Este módulo ya no envía códigos al servidor vía HTTP.
#
# Motivo: el lector global de teclado (biblioteca `keyboard`) captura
# los keystrokes al mismo tiempo que el input del navegador (`#codigoScanner`).
# Cuando ambos estaban activos, cada escaneo generaba dos peticiones a
# /api/procesar_codigo/: una desde el navegador (con cookie de sesión correcta)
# y otra desde este módulo (sin cookie → sesión huérfana, stock corrupto).
#
# El navegador maneja el escaneo de forma nativa a través del input focalizado
# en el modal de operación. No se necesita ningún hook de OS para el flujo normal.
#
# Se mantiene la función `iniciar_lector` como stub para que run.py y manage.py
# no fallen al importar este módulo. Si en el futuro se necesita un hook de OS
# para otro propósito (ej: detectar escaneos fuera del foco del navegador),
# debe implementarse sin realizar peticiones HTTP al servidor.


def iniciar_lector():
    """Stub. El escaneo se maneja directamente en el navegador."""
    pass

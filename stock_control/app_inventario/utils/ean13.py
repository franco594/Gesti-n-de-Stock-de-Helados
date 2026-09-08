"""
Validación y parseo centralizado de códigos EAN-13.

Formato interno del sistema:
  Posiciones (base-0):  0    1    2-4   5-7    8    9-11   12
  Significado:         '2'  '0'  PLU  relleno  kg  dec_kg  check

  - Posición 0:    siempre '2' (código de peso variable)
  - Posiciones 2-4: PLU del producto (3 dígitos, ej. '001')
  - Posición 8:    kilogramos enteros
  - Posiciones 9-11: kilogramos decimales (3 dígitos)
  - Posición 12:   dígito verificador EAN-13

Ejemplo: "2000100045001"
  PLU = [2:5] = '001', kg = int([8]) = 4, dec = [9:12] = '500'
  peso = 4.500 kg

Funciones exportadas:
  validar_ean13(codigo)           → (ok: bool, motivo: str)
  validar_ean13_estricto(codigo)  → (ok: bool, motivo: str)
  calcular_digito_verificador(12) → int
  parsear_codigo_barras(codigo)   → dict
"""


def calcular_digito_verificador(codigo_12: str) -> int:
    """
    Calcula el dígito verificador EAN-13 para los primeros 12 dígitos.

    Algoritmo estándar EAN-13:
      1. Sumar dígitos en posiciones pares   (índices 0, 2, 4 …) × 1.
      2. Sumar dígitos en posiciones impares (índices 1, 3, 5 …) × 3.
      3. check = (10 - (total % 10)) % 10

    Ejemplo: "590123412345" → 7
    """
    if len(codigo_12) != 12 or not codigo_12.isdigit():
        raise ValueError(f"Se esperaban 12 dígitos, recibido: {codigo_12!r}")
    total = sum(
        int(d) * (3 if i % 2 else 1)
        for i, d in enumerate(codigo_12)
    )
    return (10 - (total % 10)) % 10


def validar_ean13(codigo: str) -> tuple[bool, str]:
    """
    Valida que un código cumpla el formato EAN-13 básico:
    exactamente 13 dígitos numéricos.

    No verifica el dígito verificador en los endpoints de operaciones —
    los lectores de barcode del cliente generan códigos de peso variable
    cuyo DV puede diferir del estándar EAN-13 según la báscula.
    Para validar el DV explícitamente, usar `calcular_digito_verificador`.

    Retorna (True, "") si válido; (False, motivo) si no.
    """
    if len(codigo) != 13:
        return False, f"Debe tener 13 dígitos (recibido: {len(codigo)})"
    if not codigo.isdigit():
        return False, "Solo se permiten dígitos numéricos"
    return True, ""


def validar_ean13_estricto(codigo: str) -> tuple[bool, str]:
    """
    Validación EAN-13 estricta: longitud, dígitos Y dígito verificador.

    Usar cuando el origen del código es confiable (lectores configurados
    con EAN-13 real). Los endpoints de operaciones usan `validar_ean13`
    (no estricta) para compatibilidad con básculas de peso variable.

    Retorna (True, "") si válido; (False, motivo) si no.
    """
    ok, motivo = validar_ean13(codigo)
    if not ok:
        return ok, motivo
    esperado = calcular_digito_verificador(codigo[:12])
    real = int(codigo[12])
    if real != esperado:
        return False, f"Dígito verificador incorrecto (esperado {esperado}, recibido {real})"
    return True, ""


def parsear_codigo_barras(codigo: str) -> dict:
    """
    Extrae los campos semánticos de un EAN-13 del sistema de baldes.

    Retorna un dict con:
      {
        "codigo":                 str,   # código original completo
        "plu":                    str,   # PLU de 3 dígitos (posiciones 2-4)
        "peso_etiqueta":          float, # peso en kg según etiqueta (posiciones 8-11)
        "digito_verificador_valido": bool, # True si el DV del código coincide
      }

    Si el código no tiene 13 dígitos numéricos, retorna None para plu y
    peso_etiqueta, y digito_verificador_valido=False.

    El campo `plu` solo se extrae si el código empieza con '2'
    (código de peso variable). Para códigos externos que no siguen el
    formato interno del sistema, plu y peso_etiqueta serán None.

    Nunca lanza excepción: siempre retorna el dict (incluso con datos parciales).
    """
    resultado: dict = {
        "codigo": codigo,
        "plu": None,
        "peso_etiqueta": None,
        "digito_verificador_valido": False,
    }

    # Validación básica de formato
    if not isinstance(codigo, str) or len(codigo) != 13 or not codigo.isdigit():
        return resultado

    # Verificar dígito verificador
    try:
        esperado = calcular_digito_verificador(codigo[:12])
        resultado["digito_verificador_valido"] = (int(codigo[12]) == esperado)
    except Exception:
        pass  # resultado ya tiene False

    # Extraer PLU y peso solo para códigos de peso variable (prefijo '2')
    if codigo[0] == "2":
        resultado["plu"] = codigo[2:5]  # posiciones 2-4

        try:
            kg_enteros = int(codigo[8])         # posición 8
            kg_decimales = codigo[9:12]          # posiciones 9-11
            resultado["peso_etiqueta"] = float(f"{kg_enteros}.{kg_decimales}")
        except (ValueError, IndexError):
            pass  # peso_etiqueta queda en None

    return resultado

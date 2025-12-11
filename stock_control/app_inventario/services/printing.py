from datetime import datetime
from django.conf import settings
from django.db.models import Sum, Count
from decimal import Decimal


LINE = "-" * 42

def _send_to_spooler(data: bytes, printer_name: str):
    import win32print
    h = win32print.OpenPrinter(printer_name)
    try:
        job = win32print.StartDocPrinter(h, 1, ("Comprobante", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)

def _dummy():
    from escpos.printer import Dummy
    d = Dummy()
    d.charcode('CP858')
    return d

# ==========================
# Cálculo de costos por kilo
# ==========================

CAT1_NOMBRES = {
    "LIMON",
    "FRUTILLA AL AGUA",
    "FRAMBUESA",
    "AMERICANA",
    "GRANIZADO",
    "BANANA SPLIT",
    "TRAMONTANA",
    "VAINILLA",
    "CHOCOTORTA",
    "FRUTILLA A LA CREMA",
    "CREMA OREO",
    "CREMA DEL CIELO",
    "MENTA GRANIZADA",
    "MASCARPONE CON FRUTOS",
    "PANNACOTTA",
    "DCE DE LECHE",
    "DCE DE LECHE GRANIZADO",
    "CHOCOLATE",
}

CAT2_NOMBRES = {
    "CHOCOLATE C/ALMENDRAS",
    "CABSHA",
    "AMARGO",
    "SAMBAYON",
}

CAT3_NOMBRES = {
    "CHOCO DUBAI",
    "PISTACHO",
}

PRECIO_CAT1 = Decimal("12500")
PRECIO_CAT2 = Decimal("13500")
PRECIO_CAT3 = Decimal("14500")

PRECIO_PLU_ALTO_DEFAULT = Decimal("15000")
PRECIO_PLU_ALTO_PISTACHO = Decimal("18000")


def _norm(nombre: str) -> str:
    """
    Normaliza el nombre para matchear contra las listas:
    - mayúsculas
    - espacios colapsados
    """
    return " ".join((nombre or "").strip().upper().split())


def costo_por_kilo(nombre_producto: str, plu: str) -> Decimal:
    """
    Devuelve el costo por kilo según:
    - Categoría por gusto (Cat1 / Cat2 / Cat3)
    - Rango de PLU (1–99 vs 100–199)
    - Pistacho especial en PLU 100–199
    """
    nombre = _norm(nombre_producto)

    # Intentamos parsear PLU a int (por si es "001", "010", etc.)
    try:
        plu_int = int(plu)
    except Exception:
        plu_int = None

    # PLU alto (100–199) tiene precios especiales
    if plu_int is not None and 100 <= plu_int <= 199:
        if "PISTACHO" in nombre:
            return PRECIO_PLU_ALTO_PISTACHO
        return PRECIO_PLU_ALTO_DEFAULT

    # PLU 1–99 => usamos las categorías por gusto
    if nombre in CAT1_NOMBRES:
        return PRECIO_CAT1
    if nombre in CAT2_NOMBRES:
        return PRECIO_CAT2
    if nombre in CAT3_NOMBRES:
        return PRECIO_CAT3

    # Si no matchea, usamos Cat1 como default (podés cambiar esto)
    return PRECIO_CAT1


def print_grupo_movimiento(grupo_id: int, copias: int = 1):
    from app_inventario.models import GrupoMovimiento, RegistroMovimiento
    g = GrupoMovimiento.objects.select_related("destino").get(grupo_id=grupo_id)




    # Detalle agrupado por producto
    qs = (
        RegistroMovimiento.objects
        .filter(grupo_id=grupo_id)
        .select_related("producto")
        .values("producto__nombre", "producto__plu")
        .annotate(n=Count("id"), kg=Sum("peso"))
        .order_by("producto__nombre")
    )

    # Totales (usa campos del grupo si ya están)
    agg = {"n": sum(r["n"] for r in qs), "kg": sum((r["kg"] or 0) for r in qs)}
    total_items = g.cantidad_items or agg["n"] or 0
    total_kilos = float(g.total_peso or agg["kg"] or 0)

    p = _dummy()
    for _ in range(max(1, int(copias))):
        # (opcional) logo
        if getattr(settings, "PRINT_LOGO_PATH", ""):
            try:
                p.set(align="center")
                p.image(settings.PRINT_LOGO_PATH)
                p.textln("")
            except Exception:
                pass

        # Encabezado
        p.set(align="center", font="b", width=2, height=2, bold=True)
        p.textln(getattr(settings, "NOMBRE_COMERCIO", "Gestión de Stock"))

        p.set(align="center", font="b", bold=True)
        p.textln(f"MOVIMIENTO #{g.grupo_id}")

        p.set(align="center", font="a")
        fecha = g.fecha or datetime.now()
        p.textln(fecha.strftime("%d/%m/%Y %H:%M"))
        p.textln("Tipo: " + ("INGRESO" if g.tipo == "ingreso" else "RETIRO"))
        if g.tipo == "ingreso" and g.origen:
            p.textln(f"Origen: {g.origen}")
        if g.tipo != "ingreso" and g.destino:
            p.textln(f"Salida: {g.destino}")

        p.textln(LINE)

        # Tabla
        # Tabla
    total_costo = Decimal("0")

    if qs:
        p.set(align="left", font="a", bold=True)
        # Cabecera con columna Total
        p.textln("Producto          Unid  Kilos      Total")
        p.set(align="left", font="a")

        for r in qs:
            nombre_raw = r["producto__nombre"] or ""
            plu_raw = r.get("producto__plu") or ""
            kg = Decimal(str(r["kg"] or 0))
            unidades_int = int(r["n"])

            # Cálculo de costo solo para RETIROS
            costo_linea = Decimal("0")
            if g.tipo in ("salida", "retiro"):
                precio_kg = costo_por_kilo(nombre_raw, plu_raw)
                costo_linea = (kg * precio_kg).quantize(Decimal("0.01"))
                total_costo += costo_linea

            # Armado de fila (42 caracteres aprox)
            # 18 (nombre) + 4 (unid) + 7 (kg) + 11 (total) = 40-41
            nombre = nombre_raw[:18].ljust(18)
            unidades = str(unidades_int).rjust(4)
            kilos_str = f"{float(kg):.3f}".rjust(7)
            total_str = (f"{int(costo_linea):d}" if costo_linea else "0").rjust(11)

            p.textln(f"{nombre}{unidades}{kilos_str}{total_str}")

        p.textln(LINE)


        # Totales
        p.set(align="left", font="b", bold=True)
        p.textln(f"Total baldes: {total_items}")
        p.textln(f"Total kilos:  {total_kilos:.3f} kg")

        # Total en $ solo para retiros
        if g.tipo in ("salida", "retiro"):
            p.textln(f"Total costo: ${int(total_costo):d}")

        p.textln(LINE)

        # Identificador
        p.set(align="center")
        try:
            p.barcode(str(g.grupo_id), "CODE39", height=64)
        except Exception:
            pass

        p.textln("")
        p.set(align="center", font="a")
        p.textln("\n")
        p.cut()

    _send_to_spooler(p.output, getattr(settings, "EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt"))


def _fmt_kilos(kg):
    try:
        return f"{float(kg):.3f} kg"
    except Exception:
        return str(kg)





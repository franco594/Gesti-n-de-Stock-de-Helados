from datetime import datetime
from django.conf import settings
from django.db.models import Sum, Count, Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from decimal import Decimal

from app_inventario.models import ProductoFijo


LINE = "-" * 42


def _send_to_spooler(data: bytes, printer_name: str):
    import win32print
    h = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(h, 1, ("Comprobante", None, "RAW"))
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
    "LIMON", "FRUTILLA AL AGUA", "FRAMBUESA", "AMERICANA", "GRANIZADO",
    "BANANA SPLIT", "TRAMONTANA", "VAINILLA", "CHOCOTORTA",
    "FRUTILLA A LA CREMA", "CREMA OREO", "CREMA DEL CIELO",
    "MENTA GRANIZADA", "MASCARPONE CON FRUTOS", "PANNACOTTA",
    "DCE DE LECHE", "DCE DE LECHE GRANIZADO", "CHOCOLATE",
}

CAT2_NOMBRES = {
    "CHOCOLATE C/ALMENDRAS", "CABSHA", "AMARGO", "SAMBAYON",
}

CAT3_NOMBRES = {
    "CHOCO DUBAI", "PISTACHO",
}

PRECIO_CAT1 = Decimal("12500")
PRECIO_CAT2 = Decimal("13500")
PRECIO_CAT3 = Decimal("14500")

PRECIO_PLU_ALTO_DEFAULT = Decimal("15000")
PRECIO_PLU_ALTO_PISTACHO = Decimal("18000")


def _norm(nombre: str) -> str:
    return " ".join((nombre or "").strip().upper().split())


def costo_por_kilo(nombre_producto: str, plu: str) -> Decimal:
    nombre = _norm(nombre_producto)
    try:
        plu_int = int(plu)
    except Exception:
        plu_int = None

    if plu_int is not None and 100 <= plu_int <= 199:
        if "PISTACHO" in nombre:
            return PRECIO_PLU_ALTO_PISTACHO
        return PRECIO_PLU_ALTO_DEFAULT

    if nombre in CAT1_NOMBRES:
        return PRECIO_CAT1
    if nombre in CAT2_NOMBRES:
        return PRECIO_CAT2
    if nombre in CAT3_NOMBRES:
        return PRECIO_CAT3

    return PRECIO_CAT1


# ==========================
# COMPROBANTE DE MOVIMIENTO
# ==========================

def print_grupo_movimiento(grupo_id: int, copias: int = 1):
    from app_inventario.models import GrupoMovimiento, RegistroMovimiento

    g = GrupoMovimiento.objects.select_related("destino").get(grupo_id=grupo_id)

    # ❌ NO imprimir si es INGRESO
    if g.tipo == "ingreso":
        return

    qs = (
        RegistroMovimiento.objects
        .filter(grupo_id=grupo_id)
        .select_related("producto")
        .values("producto__nombre", "producto__plu")
        .annotate(n=Count("id"), kg=Sum("peso"))
        .order_by("producto__nombre")
    )

    total_items = g.cantidad_items or sum(r["n"] for r in qs)
    total_kilos = float(g.total_peso or sum((r["kg"] or 0) for r in qs))

    p = _dummy()
    total_costo = Decimal("0")

    for _ in range(max(1, int(copias))):
        p.set(align="center", font="b", width=2, height=2, bold=True)
        p.textln(getattr(settings, "NOMBRE_COMERCIO", "Gestión de Stock"))

        p.set(align="center", font="b", bold=True)
        p.textln(f"MOVIMIENTO #{g.grupo_id}")

        fecha = g.fecha or datetime.now()
        p.set(align="center", font="a")
        p.textln(fecha.strftime("%d/%m/%Y %H:%M"))
        p.textln("Tipo: RETIRO")
        if g.destino:
            p.textln(f"Salida: {g.destino}")

        p.textln(LINE)

        p.set(align="left", font="a", bold=True)
        p.textln("Producto          Unid  Kilos      Total")
        p.set(align="left", font="a")

        for r in qs:
            nombre = r["producto__nombre"] or ""
            plu = r["producto__plu"] or ""
            kg = Decimal(str(r["kg"] or 0))
            unidades = int(r["n"])

            precio = costo_por_kilo(nombre, plu)
            costo = (kg * precio).quantize(Decimal("0.01"))
            total_costo += costo

            p.textln(
                f"{nombre[:18].ljust(18)}"
                f"{str(unidades).rjust(4)}"
                f"{f'{float(kg):.3f}'.rjust(7)}"
                f"{str(int(costo)).rjust(11)}"
            )

        p.textln(LINE)
        p.set(align="left", font="b", bold=True)
        p.textln(f"Total baldes: {total_items}")
        p.textln(f"Total kilos:  {total_kilos:.3f} kg")
        p.textln(f"Total costo: ${int(total_costo)}")
        p.textln(LINE)

        p.cut()

    _send_to_spooler(p.output, getattr(settings, "EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt"))


# ==========================
# STOCK TOTAL
# ==========================

def print_stock_total():
    base = (
        ProductoFijo.objects
        .annotate(
            cant=Count("stockbalde", filter=Q(stockbalde__is_activo=True)),
            kg=Sum("stockbalde__peso", filter=Q(stockbalde__is_activo=True)),
            plu_int=Cast("plu", IntegerField()),
        )
        .filter(cant__gt=0)
    )

    heladeria = base.filter(plu_int__gte=1, plu_int__lte=99).order_by("nombre")
    gastronomicos = base.filter(plu_int__gte=100, plu_int__lte=199).order_by("nombre")

    p = _dummy()

    p.set(align="center", font="b", width=2, height=2, bold=True)
    p.textln(getattr(settings, "NOMBRE_COMERCIO", "Gestión de Stock"))
    p.textln("STOCK TOTAL")

    ahora = datetime.now()
    p.set(align="center", font="a")
    p.textln(ahora.strftime("%d/%m/%Y %H:%M"))
    p.textln(LINE)

    p.set(align="left", font="a", bold=True)
    p.textln("Producto           Cant   Kilos")
    p.set(align="left", font="a")

    total_baldes = 0
    total_kilos = 0.0

    def imprimir_seccion(titulo, qs):
        nonlocal total_baldes, total_kilos
        p.set(align="center", font="b", bold=True)
        p.textln(titulo)
        p.set(align="left")
        p.textln(LINE)

        for prod in qs:
            cant = int(prod.cant or 0)
            kg = float(prod.kg or 0)

            total_baldes += cant
            total_kilos += kg

            bajo = ""
            if prod.stock_minimo is not None and cant < prod.stock_minimo:
                bajo = " !"

            p.textln(
                f"{prod.nombre[:18].ljust(18)}"
                f"{str(cant).rjust(4)}"
                f"{f'{kg:.3f}'.rjust(8)}"
                f"{bajo}"
            )
        p.textln("")

    imprimir_seccion("HELADERIA (PLU 1-99)", heladeria)
    imprimir_seccion("GASTRONOMICOS (PLU 100-199)", gastronomicos)

    p.textln(LINE)
    p.set(align="left", font="b", bold=True)
    p.textln(f"Total baldes: {total_baldes}")
    p.textln(f"Total kilos:  {total_kilos:.3f} kg")
    p.textln(LINE)

    p.cut()
    _send_to_spooler(p.output, getattr(settings, "EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt"))

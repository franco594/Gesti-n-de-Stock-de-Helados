from datetime import datetime
from django.conf import settings
from django.db.models import Sum, Count, Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from decimal import Decimal
import pytz

from app_inventario.models import ProductoFijo


LINE = "-" * 42

# ─── Zona horaria local ────────────────────────────────────────────────────
_TZ_LOCAL = pytz.timezone("America/Argentina/Buenos_Aires")


def _ahora_local() -> datetime:
    """Devuelve la hora actual en la zona horaria local (Argentina)."""
    return datetime.now(_TZ_LOCAL)


def _a_local(dt: datetime) -> datetime:
    """
    Convierte un datetime (con o sin tzinfo) a hora local Argentina.
    - Si viene de la BD con USE_TZ=True → tiene tzinfo UTC → convierte correctamente.
    - Si por alguna razón llega naive → lo asume UTC y convierte.
    """
    if dt is None:
        return _ahora_local()
    if dt.tzinfo is None:
        # naive → asumir UTC
        dt = pytz.utc.localize(dt)
    return dt.astimezone(_TZ_LOCAL)
# ──────────────────────────────────────────────────────────────────────────


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


def _norm(nombre: str) -> str:
    return " ".join((nombre or "").strip().upper().split())


def _get_precios() -> dict:
    """Carga precios desde la DB con fallback a valores hardcodeados."""
    defaults = {
        'precio_cat1':                  Decimal('12500'),
        'precio_cat2':                  Decimal('13500'),
        'precio_cat3':                  Decimal('14500'),
        'precio_gastronomico':          Decimal('15000'),
        'precio_gastronomico_pistacho': Decimal('18000'),
    }
    try:
        from app_inventario.models import ConfiguracionSistema
        db = {c.clave: Decimal(c.valor) for c in ConfiguracionSistema.objects.filter(clave__in=defaults)}
        return {**defaults, **db}
    except Exception:
        return defaults


def costo_por_kilo(nombre_producto: str, plu: str, precios: dict = None) -> Decimal:
    if precios is None:
        precios = _get_precios()
    nombre = _norm(nombre_producto)
    try:
        plu_int = int(plu)
    except Exception:
        plu_int = None

    if plu_int is not None and 100 <= plu_int <= 199:
        if "PISTACHO" in nombre:
            return precios['precio_gastronomico_pistacho']
        return precios['precio_gastronomico']

    if nombre in CAT1_NOMBRES:
        return precios['precio_cat1']
    if nombre in CAT2_NOMBRES:
        return precios['precio_cat2']
    if nombre in CAT3_NOMBRES:
        return precios['precio_cat3']

    return precios['precio_cat1']


# ==========================
# COMPROBANTE DE MOVIMIENTO
# ==========================

def print_grupo_movimiento(grupo_id: int, copias: int = 1):
    from app_inventario.models import GrupoMovimiento, RegistroMovimiento

    g = GrupoMovimiento.objects.select_related("destino").get(grupo_id=grupo_id)

    if g.tipo == "ingreso":
        return

    # Listar items individuales (no agregados) para mostrar el codigo_barras de cada balde.
    items = list(
        RegistroMovimiento.objects
        .filter(grupo_id=grupo_id)
        .select_related("producto")
        .order_by("producto__nombre", "id")
    )

    total_items = len(items)
    total_kilos = float(g.total_peso or sum(float(i.peso or 0) for i in items))
    es_devolucion = g.tipo == "devolucion"

    p = _dummy()
    precios = _get_precios()

    for _ in range(max(1, int(copias))):
        # ── Encabezado ──────────────────────────────────────────────
        p.set(align="center", font="b", width=2, height=2, bold=True)
        p.textln(getattr(settings, "NOMBRE_COMERCIO", "Gestión de Stock"))

        p.set(align="center", font="b", bold=True)
        p.textln(f"MOVIMIENTO #{g.grupo_id}")

        fecha_local = _a_local(g.fecha)
        p.set(align="center", font="a")
        p.textln(fecha_local.strftime("%d/%m/%Y %H:%M"))

        if es_devolucion:
            p.textln("Tipo: RE-INGRESO")
            if g.origen:
                p.textln(f"Origen: {g.origen}")
        else:
            p.textln("Tipo: RETIRO")
            if g.destino:
                p.textln(f"Salida: {g.destino}")

        p.textln(LINE)

        # ── Detalle por balde ────────────────────────────────────────
        # Cada ítem ocupa dos líneas:
        #   Línea 1: Producto | Kilos | (Total si es retiro)
        #   Línea 2:   codigo_barras EAN-13
        #
        # Ancho de papel: 42 caracteres (LINE)
        # Retiro  → "Producto(18) Kilos(6) Total(10)"  = 34 chars
        # Devol.  → "Producto(20) Kilos(7)"             = 27 chars

        total_costo = Decimal("0")  # se recalcula por copia para evitar acumulación

        if es_devolucion:
            p.set(align="left", font="a", bold=True)
            p.textln("Producto             Kilos")
            p.set(align="left", font="a")
            for item in items:
                nombre = (item.producto.nombre or "")
                kg = float(item.peso or 0)
                p.textln(
                    f"{nombre[:20].ljust(20)}"
                    f"{f'{kg:.3f}'.rjust(7)}"
                )
                cb = (item.codigo_barras or "").strip()
                if cb:
                    p.textln(f"  {cb}")
        else:
            p.set(align="left", font="a", bold=True)
            p.textln("Producto           Kilos      Total")
            p.set(align="left", font="a")
            for item in items:
                nombre = (item.producto.nombre or "")
                plu = (item.producto.plu or "")
                kg = Decimal(str(item.peso or 0))
                precio = costo_por_kilo(nombre, plu, precios)
                costo = (kg * precio).quantize(Decimal("0.01"))
                total_costo += costo
                p.textln(
                    f"{nombre[:18].ljust(18)}"
                    f"{f'{float(kg):.3f}'.rjust(7)}"
                    f"{str(int(costo)).rjust(11)}"
                )
                cb = (item.codigo_barras or "").strip()
                if cb:
                    p.textln(f"  {cb}")

        # ── Totales ──────────────────────────────────────────────────
        p.textln(LINE)
        p.set(align="left", font="b", bold=True)
        p.textln(f"Total baldes: {total_items}")
        p.textln(f"Total kilos:  {total_kilos:.3f} kg")
        if not es_devolucion:
            p.textln(f"Total costo: ${int(total_costo)}")
        p.textln(LINE)

        p.cut()

    _send_to_spooler(p.output, getattr(settings, "EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt"))


# ==========================
# STOCK TOTAL
# ==========================

def print_stock_total():
    # Incluye todos los PLUs activos, incluso los que tienen 0 baldes en cámara.
    # PLUs inactivos (sabores discontinuados) no aparecen.
    base = (
        ProductoFijo.objects
        .filter(is_activo=True)
        .annotate(
            cant=Count("stockbalde", filter=Q(stockbalde__is_activo=True)),
            kg=Sum("stockbalde__peso", filter=Q(stockbalde__is_activo=True)),
            plu_int=Cast("plu", IntegerField()),
        )
    )

    helados       = base.filter(plu_int__gte=1,   plu_int__lte=88).order_by("nombre")
    barras_tortas = base.filter(plu_int__gte=89,  plu_int__lte=98).order_by("nombre")
    gastronomicos = base.filter(plu_int__gte=100, plu_int__lte=199).order_by("nombre")

    p = _dummy()

    p.set(align="center", font="b", width=2, height=2, bold=True)
    p.textln(getattr(settings, "NOMBRE_COMERCIO", "Gestión de Stock"))
    p.textln("STOCK TOTAL")

    ahora = _ahora_local()
    p.set(align="center", font="a")
    p.textln(ahora.strftime("%d/%m/%Y %H:%M"))
    p.textln(LINE)

    p.set(align="left", font="a", bold=True)
    p.textln("Producto           Cant   Kilos")
    p.set(align="left", font="a")

    total_baldes = 0
    total_kilos  = 0.0

    def imprimir_seccion(titulo, qs):
        nonlocal total_baldes, total_kilos
        prods = list(qs)
        if not prods:
            return 0, 0.0

        p.set(align="center", font="b", bold=True)
        p.textln(titulo)
        p.set(align="left", font="a", bold=False)
        p.textln(LINE)

        sec_baldes = 0
        sec_kilos  = 0.0
        for prod in prods:
            cant = int(prod.cant or 0)
            kg   = float(prod.kg or 0)
            sec_baldes   += cant
            sec_kilos    += kg
            total_baldes += cant
            total_kilos  += kg

            bajo = " !" if (prod.stock_minimo is not None and cant < prod.stock_minimo) else ""
            p.textln(
                f"{prod.nombre[:18].ljust(18)}"
                f"{str(cant).rjust(4)}"
                f"{f'{kg:.3f}'.rjust(8)}"
                f"{bajo}"
            )

        p.set(align="left", font="b", bold=True)
        p.textln(f"  Subtotal: {sec_baldes} baldes  {sec_kilos:.3f} kg")
        p.set(align="left", font="a", bold=False)
        p.textln("")
        return sec_baldes, sec_kilos

    sub_h_b,  sub_h_k  = imprimir_seccion("HELADOS (PLU 1-88)",         helados)
    sub_bt_b, sub_bt_k = imprimir_seccion("BARRAS Y TORTAS (PLU 89-98)", barras_tortas)
    sub_g_b,  sub_g_k  = imprimir_seccion("GASTRONOMICOS (PLU 100-199)", gastronomicos)

    p.textln(LINE)
    p.set(align="left", font="b", bold=True)
    p.textln(f"Helados:      {sub_h_b:>3}  {sub_h_k:.3f} kg")
    p.textln(f"Barras/Tortas:{sub_bt_b:>3}  {sub_bt_k:.3f} kg")
    p.textln(f"Gastronomicos:{sub_g_b:>3}  {sub_g_k:.3f} kg")
    p.textln(LINE)
    p.textln(f"TOTAL:        {total_baldes:>3}  {total_kilos:.3f} kg")
    p.textln(LINE)

    p.cut()
    _send_to_spooler(p.output, getattr(settings, "EPSON_PRINTER_NAME", "EPSON TM-T88V Receipt"))
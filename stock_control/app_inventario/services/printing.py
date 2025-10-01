from datetime import datetime
from django.conf import settings
from django.db.models import Sum, Count

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

def print_grupo_movimiento(grupo_id: int, copias: int = 1):
    from app_inventario.models import GrupoMovimiento, RegistroMovimiento
    g = GrupoMovimiento.objects.select_related("destino").get(grupo_id=grupo_id)

    # Detalle agrupado por producto
    qs = (
        RegistroMovimiento.objects
        .filter(grupo_id=grupo_id)
        .select_related("producto")
        .values("producto__nombre")
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
        if g.tipo == "retiro" and g.destino:
            p.textln(f"Destino: {getattr(g.destino, 'nombre', '')}")
        p.textln(LINE)

        # Tabla
        if qs:
            p.set(align="left", font="a", bold=True)
            p.textln("Producto                 Unid   Kilos")
            p.set(align="left", font="a")
            for r in qs:
                nombre = (r["producto__nombre"] or "")[:22].ljust(22)
                unidades = str(r["n"]).rjust(5)
                kilos = f"{float(r['kg'] or 0):.3f}".rjust(8)
                p.textln(f"{nombre} {unidades} {kilos}")
            p.textln(LINE)

        # Totales
        p.set(align="left", font="b", bold=True)
        p.textln(f"Total baldes: {total_items}")
        p.textln(f"Total kilos:  {total_kilos:.3f} kg")
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



def demo_print():
    class Fake:
        id = 1234
        tipo = "I"
        fecha = datetime.now()
        peso = 1.234
        usuario = "admin"
        boca_salida = "Cámara"
        class P: nombre = "Helado crema americana"
        producto = P()
    print_movimiento(Fake())

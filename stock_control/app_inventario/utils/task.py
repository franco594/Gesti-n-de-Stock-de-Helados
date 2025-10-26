from datetime import date as date_cls   # si no lo tenés ya
from django.core.mail import EmailMultiAlternatives
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta, time as dt_time
from app_inventario.models import RegistroMovimiento, StockBalde
from datetime import date
from typing import Optional


def enviar_reporte_stock(fecha: Optional[date] = None):
    """
    Envía el reporte del día indicado por 'fecha' (zona horaria local de Django).
    Si 'fecha' es None, usa la fecha local actual.
    - Movimientos (ingresos/retiros) filtrados al día 'fecha'
    - Stock actual (is_activo=True) al momento del envío
    """
    if fecha is None:
        fecha = timezone.localdate()

    # Ventana del día [00:00, 24:00) de 'fecha' en TZ actual
    tz = timezone.get_current_timezone()
    inicio_dia = timezone.make_aware(timezone.datetime.combine(fecha, dt_time.min), tz)
    fin_dia    = inicio_dia + timedelta(days=1)

    # Movimientos del día
    movimientos_del_dia = RegistroMovimiento.objects.filter(timestamp__range=(inicio_dia, fin_dia))
    ingresos_del_dia = movimientos_del_dia.filter(tipo='ingreso')
    retiros_del_dia  = movimientos_del_dia.filter(tipo='salida')

    total_ingresado = ingresos_del_dia.aggregate(total=Sum('peso'))['total'] or 0
    total_retirado  = retiros_del_dia.aggregate(total=Sum('peso'))['total'] or 0

    # Agrupaciones del día
    origenes_qs = (
        ingresos_del_dia.values('origen')
        .annotate(total=Sum('peso'))
        .order_by('-total')
    )
    destinos_qs = (
        retiros_del_dia.values('boca_salida')
        .annotate(total=Sum('peso'))
        .order_by('-total')
    )

    # ⚠️ Materializamos en listas para poder chequear si están vacías
    origenes = list(origenes_qs)
    destinos = list(destinos_qs)

    # Stock actual (activos)
    stock_por_producto = list(
        StockBalde.objects.filter(is_activo=True)
        .values('producto__nombre')
        .annotate(total_kilos=Sum('peso'), cantidad=Count('id'))
        .order_by('producto__nombre')
    )

    total_kilos_activos = float(sum((s['total_kilos'] or 0) for s in stock_por_producto))
    total_baldes_activos = sum(s['cantidad'] for s in stock_por_producto)

    # ---------- Texto plano (fallback) ----------
    text_lines = [
        f"REPORTE DIARIO - {fecha.strftime('%d/%m/%Y')}",
        "",
        f"Total ingresado hoy: {float(total_ingresado):.2f} kg",
        f"Total retirado hoy: {float(total_retirado):.2f} kg",
        "",
        "Orígenes de ingresos (hoy):"
    ]
    if len(origenes) > 0:
        for o in origenes:
            if o['origen']:
                text_lines.append(f"- {o['origen']}: {float(o['total']):.2f} kg")
    else:
        text_lines.append("(Sin ingresos hoy)")

    text_lines.append("\nDestinos de retiros (hoy):")
    if len(destinos) > 0:
        for d in destinos:
            if d['boca_salida']:
                text_lines.append(f"- {d['boca_salida']}: {float(d['total']):.2f} kg")
    else:
        text_lines.append("(Sin retiros hoy)")

    text_lines.append("\nSTOCK ACTUAL (al cierre):")
    if len(stock_por_producto) > 0:
        text_lines.append(f"{'Producto':<25} {'Baldes':>6} {'Kilos':>10} {'%':>6}")
        text_lines.append("-" * 55)
        for s in stock_por_producto:
            nombre = s['producto__nombre']
            kilos  = float(s['total_kilos'] or 0)
            cant   = s['cantidad']
            pct    = (kilos / total_kilos_activos * 100) if total_kilos_activos else 0
            text_lines.append(f"{nombre:<25} {cant:>6} {kilos:>10.2f} {pct:>5.1f}%")
        text_lines.append("-" * 55)
        text_lines.append(f"{'TOTAL':<25} {total_baldes_activos:>6} {total_kilos_activos:>10.2f} {100:>5.1f}%")
    else:
        text_lines.append("(No hay stock activo)")

    text_body = "\n".join(text_lines)

    # ---------- HTML (alineado) ----------
    table_rows = ""
    if len(stock_por_producto) > 0:
        for s in stock_por_producto:
            nombre = s['producto__nombre']
            kilos  = float(s['total_kilos'] or 0)
            cant   = s['cantidad']
            pct    = (kilos / total_kilos_activos * 100) if total_kilos_activos else 0
            table_rows += f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #eee;">{nombre}</td>
              <td style="padding:8px 10px;text-align:right;border-bottom:1px solid #eee;">{cant}</td>
              <td style="padding:8px 10px;text-align:right;border-bottom:1px solid #eee;">{kilos:.2f}</td>
              <td style="padding:8px 10px;text-align:right;border-bottom:1px solid #eee;">{pct:.1f}%</td>
            </tr>
            """

    html_body = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#111; line-height:1.4;">
      <h2 style="margin:0 0 12px;">📅 Reporte diario – {fecha.strftime('%d/%m/%Y')}</h2>

      <div style="margin:6px 0 14px;">
        <div>✅ <strong>Total ingresado hoy:</strong> {float(total_ingresado):.2f} kg</div>
        <div>📤 <strong>Total retirado hoy:</strong> {float(total_retirado):.2f} kg</div>
      </div>

      <h3 style="margin:16px 0 6px;">🔹 Orígenes de ingresos (hoy)</h3>
      {("<ul style='margin:6px 0 14px;'>" + "".join([f"<li>{o['origen']}: {float(o['total']):.2f} kg</li>" for o in origenes if o['origen']]) + "</ul>") if len(origenes) > 0 else "<div style='color:#666;margin:6px 0 14px;'>Sin ingresos hoy</div>"}

      <h3 style="margin:16px 0 6px;">🔸 Destinos de retiros (hoy)</h3>
      {("<ul style='margin:6px 0 14px;'>" + "".join([f"<li>{d['boca_salida']}: {float(d['total']):.2f} kg</li>" for d in destinos if d['boca_salida']]) + "</ul>") if len(destinos) > 0 else "<div style='color:#666;margin:6px 0 14px;'>Sin retiros hoy</div>"}

      <h3 style="margin:18px 0 8px;">📊 Stock actual al cierre</h3>
      {(
      f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:720px;border:1px solid #eee;">
        <thead>
          <tr style="background:#f7f7f7;">
            <th align="left"  style="padding:10px;border-bottom:1px solid #eee;">Producto</th>
            <th align="right" style="padding:10px;border-bottom:1px solid #eee;">Baldes</th>
            <th align="right" style="padding:10px;border-bottom:1px solid #eee;">Kilos</th>
            <th align="right" style="padding:10px;border-bottom:1px solid #eee;">% del total</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
          <tr>
            <td style="padding:10px;font-weight:600;border-top:2px solid #ddd;">TOTAL</td>
            <td style="padding:10px;text-align:right;font-weight:600;border-top:2px solid #ddd;">{total_baldes_activos}</td>
            <td style="padding:10px;text-align:right;font-weight:600;border-top:2px solid #ddd;">{total_kilos_activos:.2f}</td>
            <td style="padding:10px;text-align:right;font-weight:600;border-top:2px solid #ddd;">100.0%</td>
          </tr>
        </tbody>
      </table>
      """
      ) if len(stock_por_producto) > 0 else "<div style='color:#666;'>No hay stock activo</div>"}
    </div>
    """

    subject = f"Reporte de stock diario - {fecha.strftime('%d/%m/%Y')}"
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,  # fallback
        from_email="francopiero594@gmail.com",
        to=["portofinotuyu@yahoo.com.ar"],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)

    print(f"✅ Reporte diario de {fecha.strftime('%d/%m/%Y')} enviado correctamente (HTML + texto).")

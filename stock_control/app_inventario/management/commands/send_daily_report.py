from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from app_inventario.utils.task import enviar_reporte_stock

class Command(BaseCommand):
    help = "Envía el reporte diario de stock. Usa la fecha local (hoy) por defecto."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="Fecha YYYY-MM-DD (opcional)")

    def handle(self, *args, **opts):
        if opts.get("date"):
            try:
                fecha = datetime.strptime(opts["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(self.style.ERROR("Formato --date inválido. Use YYYY-MM-DD."))
                return
        else:
            fecha = timezone.localdate()

        enviar_reporte_stock(fecha)  # tu función ya acepta 'fecha'
        self.stdout.write(self.style.SUCCESS(f"Reporte enviado para {fecha}"))

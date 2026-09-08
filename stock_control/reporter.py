# reporter.py
import os
from datetime import datetime
from argparse import ArgumentParser

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock_control.settings")

def main():
    import django; django.setup()
    from app_inventario.utils.task import enviar_reporte_stock

    p = ArgumentParser()
    p.add_argument("--date", type=str, help="YYYY-MM-DD (opcional)")
    args = p.parse_args()

    fecha = None
    if args.date:
        fecha = datetime.strptime(args.date, "%Y-%m-%d").date()
    enviar_reporte_stock(fecha)

if __name__ == "__main__":
    main()

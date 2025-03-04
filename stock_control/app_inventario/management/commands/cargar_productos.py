import pandas as pd
from app_inventario.models import ProductoFijo
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Carga productos desde un archivo Excel'

    def handle(self, *args, **kwargs):
        archivo_excel = 'productos.xlsx'  # Asegúrate de que el archivo está en la raíz del proyecto
        try:
            df = pd.read_excel(archivo_excel)
            for _, row in df.iterrows():
                ProductoFijo.objects.update_or_create(
                    plu=str(row['PLU']).zfill(3),
                    defaults={'nombre': row['Nombre'], 'stock_minimo': row.get('Stock Minimo', 5)}
                )
            self.stdout.write(self.style.SUCCESS('✔ Productos cargados exitosamente'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error cargando productos: {e}'))

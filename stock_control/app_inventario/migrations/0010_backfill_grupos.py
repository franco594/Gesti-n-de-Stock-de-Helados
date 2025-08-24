# migrations/xxxx_backfill_grupos.py
from django.db import migrations, models

def backfill(apps, schema_editor):
    RegistroMovimiento = apps.get_model('app_inventario', 'RegistroMovimiento')
    GrupoMovimiento = apps.get_model('app_inventario', 'GrupoMovimiento')

    from django.db.models import Sum, Count, Max

    qs = (RegistroMovimiento.objects
          .values('grupo_id')
          .annotate(total=Sum('peso'),
                    cantidad=Count('id'),
                    tipo_any=Max('tipo'),
                    origen_any=Max('origen'),
                    destino_any=Max('destino'),
                    fecha_any=Max('timestamp')))
    crear = []
    for row in qs:
        crear.append(GrupoMovimiento(
            grupo_id=row['grupo_id'],
            tipo=row['tipo_any'] or 'ingreso',
            origen=row['origen_any'],
            destino_id=row['destino_any'],  # FK id si existe
            total_peso=row['total'] or 0,
            cantidad_items=row['cantidad'],
        ))
    GrupoMovimiento.objects.bulk_create(crear, ignore_conflicts=True)

def reverse_backfill(apps, schema_editor):
    GrupoMovimiento = apps.get_model('app_inventario', 'GrupoMovimiento')
    GrupoMovimiento.objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [
        ('app_inventario', '0009_registromovimiento_boca_salida'),
    ]
    operations = [
        migrations.CreateModel(
            name='GrupoMovimiento',
            fields=[
                ('grupo_id', models.IntegerField(primary_key=True, serialize=False)),
                ('tipo', models.CharField(choices=[('ingreso', 'Ingreso'), ('salida', 'Retiro')], max_length=10)),
                ('origen', models.CharField(blank=True, max_length=100, null=True)),
                ('total_peso', models.FloatField(default=0)),
                ('cantidad_items', models.IntegerField(default=0)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('destino', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, to='app_inventario.bocasalida')),
            ],
        ),
        migrations.RunPython(backfill, reverse_backfill),
    ]

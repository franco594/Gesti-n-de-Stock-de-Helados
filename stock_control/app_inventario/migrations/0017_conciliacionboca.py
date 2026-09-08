from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app_inventario', '0016_alter_grupomovimiento_tipo_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConciliacionBoca',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mes', models.DateField()),
                ('stock_inicial', models.DecimalField(decimal_places=3, default=0, max_digits=8)),
                ('kg_vendidos', models.DecimalField(decimal_places=3, default=0, max_digits=8)),
                ('boca', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='app_inventario.bocasalida')),
            ],
            options={
                'verbose_name': 'Conciliación',
                'verbose_name_plural': 'Conciliaciones',
                'db_table': 'app_inventario_conciliacionboca',
                'ordering': ['-mes', 'boca__nombre'],
                'unique_together': {('boca', 'mes')},
            },
        ),
    ]

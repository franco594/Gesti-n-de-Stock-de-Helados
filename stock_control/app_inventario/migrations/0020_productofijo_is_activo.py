from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_inventario', '0019_registromovimiento_balde'),
    ]

    operations = [
        migrations.AddField(
            model_name='productofijo',
            name='is_activo',
            field=models.BooleanField(
                default=True,
                db_index=True,
                verbose_name='Activo',
            ),
        ),
    ]

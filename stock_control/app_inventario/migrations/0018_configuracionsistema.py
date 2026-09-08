from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_inventario', '0017_conciliacionboca'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracionSistema',
            fields=[
                ('clave', models.CharField(max_length=50, primary_key=True, serialize=False)),
                ('valor', models.CharField(max_length=200)),
                ('descripcion', models.CharField(blank=True, max_length=200)),
            ],
            options={
                'verbose_name': 'Configuración',
                'verbose_name_plural': 'Configuraciones',
                'db_table': 'app_inventario_configuracionsistema',
            },
        ),
    ]

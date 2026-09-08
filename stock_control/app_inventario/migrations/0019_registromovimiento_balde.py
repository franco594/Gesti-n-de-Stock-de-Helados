from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app_inventario', '0018_configuracionsistema'),
    ]

    operations = [
        migrations.AddField(
            model_name='registromovimiento',
            name='balde',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movimientos',
                to='app_inventario.stockbalde',
                verbose_name='Balde',
            ),
        ),
    ]

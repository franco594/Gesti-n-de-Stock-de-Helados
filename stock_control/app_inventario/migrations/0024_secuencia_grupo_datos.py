"""
Migración de datos: inicializar SecuenciaGrupo con el MAX(grupo_id) existente.

Garantía: no modifica ningún movimiento histórico ni grupo existente.
Solo crea o actualiza la fila "grupo_id" en app_inventario_secuenciagrupo.

Soporta --dry-run implícitamente: si se inspecciona la migración con
`python manage.py migrate --run-syncdb` o `sqlmigrate`, el bloque RunPython
solo ejecuta la función `_inicializar_secuencia`, no algo destructivo.

Para simular el efecto sin aplicar:
    python manage.py sqlmigrate app_inventario 0024
"""
from django.db import migrations


def _inicializar_secuencia(apps, schema_editor):
    """
    Lee el mayor grupo_id registrado en GrupoMovimiento y lo usa como valor
    inicial de la secuencia, para que el próximo grupo_id generado sea MAX+1.

    Si no hay grupos todavía (base nueva), el contador queda en 0 y el primer
    grupo_id que se reservará será 1.
    """
    GrupoMovimiento = apps.get_model("app_inventario", "GrupoMovimiento")
    SecuenciaGrupo = apps.get_model("app_inventario", "SecuenciaGrupo")

    max_id = (
        GrupoMovimiento.objects
        .aggregate(m=__import__("django.db.models", fromlist=["Max"]).Max("grupo_id"))
        ["m"]
    ) or 0

    SecuenciaGrupo.objects.update_or_create(
        nombre="grupo_id",
        defaults={"ultimo_valor": max_id},
    )


def _revertir_secuencia(apps, schema_editor):
    """Elimina la fila de secuencia al hacer rollback de esta migración."""
    SecuenciaGrupo = apps.get_model("app_inventario", "SecuenciaGrupo")
    SecuenciaGrupo.objects.filter(nombre="grupo_id").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app_inventario", "0023_secuencia_grupo"),
    ]

    operations = [
        migrations.RunPython(
            _inicializar_secuencia,
            reverse_code=_revertir_secuencia,
        ),
    ]

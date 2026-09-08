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
    Lee el mayor grupo_id de GrupoMovimiento Y RegistroMovimiento, y lo usa
    como valor inicial de la secuencia, para que el próximo grupo_id sea MAX+1.

    Se consideran AMBAS tablas porque históricamente pudo haber RegistroMovimiento
    con grupo_id mayor al GrupoMovimiento correspondiente (datos inconsistentes).
    Usar solo el máximo de GrupoMovimiento podría reutilizar IDs históricos.

    Si no hay registros (base nueva), el contador queda en 0 y el primer
    grupo_id que se reservará será 1.
    """
    _models = __import__("django.db.models", fromlist=["Max"])
    Max = _models.Max

    GrupoMovimiento = apps.get_model("app_inventario", "GrupoMovimiento")
    RegistroMovimiento = apps.get_model("app_inventario", "RegistroMovimiento")
    SecuenciaGrupo = apps.get_model("app_inventario", "SecuenciaGrupo")

    max_grupo = GrupoMovimiento.objects.aggregate(m=Max("grupo_id"))["m"] or 0
    max_registro = RegistroMovimiento.objects.aggregate(m=Max("grupo_id"))["m"] or 0
    max_id = max(max_grupo, max_registro)

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

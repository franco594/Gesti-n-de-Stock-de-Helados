"""
Migración correctiva: re-inicializar SecuenciaGrupo con el MAX correcto.

Problema: la versión original de la migración 0024 solo consultaba
GrupoMovimiento para calcular el valor inicial de la SecuenciaGrupo.
Si RegistroMovimiento tenía un grupo_id mayor, la secuencia quedaba baja
y los próximos grupo_ids podrían colisionar con IDs históricos.

Esta migración corrige ese valor para instalaciones que ya aplicaron la
versión errónea de 0024. Para instalaciones nuevas (o las que ya tienen
el 0024 correcto) es idempotente.

Garantía: solo modifica la fila "grupo_id" de app_inventario_secuenciagrupo.
No modifica ningún movimiento histórico ni ningún otro dato.
"""
from django.db import migrations


def _recorregir_secuencia(apps, schema_editor):
    """
    Recalcula el máximo real entre GrupoMovimiento y RegistroMovimiento
    y actualiza la SecuenciaGrupo si el valor actual es inferior.

    Usa max() para no reducir un valor ya correcto (caso de instalaciones
    que ya tenían el 0024 corregido o que crearon grupos nuevos después).
    """
    _models = __import__("django.db.models", fromlist=["Max"])
    Max = _models.Max

    GrupoMovimiento = apps.get_model("app_inventario", "GrupoMovimiento")
    RegistroMovimiento = apps.get_model("app_inventario", "RegistroMovimiento")
    SecuenciaGrupo = apps.get_model("app_inventario", "SecuenciaGrupo")

    max_grupo = GrupoMovimiento.objects.aggregate(m=Max("grupo_id"))["m"] or 0
    max_registro = RegistroMovimiento.objects.aggregate(m=Max("grupo_id"))["m"] or 0
    max_real = max(max_grupo, max_registro)

    seq, _ = SecuenciaGrupo.objects.get_or_create(
        nombre="grupo_id",
        defaults={"ultimo_valor": max_real},
    )

    # Solo actualizar si el valor actual es menor al máximo real.
    # Si ya está bien (instalación con 0024 correcto), no tocar nada.
    if seq.ultimo_valor < max_real:
        seq.ultimo_valor = max_real
        seq.save(update_fields=["ultimo_valor"])


class Migration(migrations.Migration):

    dependencies = [
        ("app_inventario", "0025_operacion_idempotente_estado_respuesta"),
    ]

    operations = [
        migrations.RunPython(
            _recorregir_secuencia,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

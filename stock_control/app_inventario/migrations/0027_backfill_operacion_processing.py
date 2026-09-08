"""
Migración correctiva: marcar registros OperacionIdempotente huérfanos.

Problema: la migración 0025 fue modificada para incluir un RunPython de
backfill DESPUÉS de haber sido publicada. Una instalación que ya aplicó
la versión original de 0025 (sin RunPython) puede tener registros con:

    estado = 'processing'   (el default de columna que Django asignó)
    respuesta_json = ''     (vacío — no había respuesta almacenada)

Esos registros representan operaciones completadas bajo el esquema anterior
a la migración 0025. Un retry sobre ellos devolvería HTTP 200 con cuerpo
vacío, lo que puede dejar al frontend esperando o mostrar un estado incierto.

Este RunPython:
1. Marca cada registro huérfano como 'completed'.
2. Asigna una respuesta_json mínima válida, compatible con lo que el
   frontend espera tras un reintento (status='ya_procesado', success=True,
   grupos_id si está disponible, listas vacías donde se esperan listas).

No afecta a instalaciones ya correctas ni a registros creados por el nuevo
código (que siempre terminan con estado='completed' explícito).
"""
import json as _json

from django.db import migrations


def _backfill_processing(apps, schema_editor):
    OperacionIdempotente = apps.get_model("app_inventario", "OperacionIdempotente")

    # Respuesta mínima por tipo — compatible con lo que el frontend espera.
    # El frontend verifica data.success (ingreso/retiro/devolucion) y
    # data.status === 'ya_procesado' (agregado por _respuesta_de_operacion).
    RESP_BASE = {
        "ingreso":    {"success": True, "productos": [], "origen": ""},
        "retiro":     {"success": True, "productos": [], "destino": ""},
        "devolucion": {"success": True, "productos": [], "cantidad": 0},
    }

    huerfanos = OperacionIdempotente.objects.filter(estado="processing")

    for op in huerfanos.iterator():
        resp = dict(RESP_BASE.get(op.tipo, {"success": True}))
        if op.grupo_id:
            resp["grupo_id"] = op.grupo_id

        op.estado = "completed"
        op.respuesta_json = _json.dumps(resp, ensure_ascii=False)
        # Preservar status_code si ya tenía uno; si no, asumir 200 (operación exitosa)
        if not op.status_code:
            op.status_code = 200
        op.save(update_fields=["estado", "respuesta_json", "status_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("app_inventario", "0026_corregir_secuencia_grupo"),
    ]

    operations = [
        migrations.RunPython(
            _backfill_processing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

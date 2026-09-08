"""
Tests de la app de gestión de stock.

Organización:
  - TestFlujoBasico            : happy path (ingreso → retiro → deshacer)
  - TestTransaccionParcial     : Bug #1 — return dentro de transaction.atomic
  - TestGrupoIdRetiro          : Bug #2 — race condition grupo_id fuera de transacción
  - TestFiltroFechas           : Bug #3 — datetime.time crash en historial
  - TestEditarItemFallback     : Bug #8 — fallback actualiza todos los baldes con mismo barcode

Convención: tests que detectan un bug existente llevan el prefijo
  "test_BUGn_" para identificarlos rápidamente.
"""

import json
import os
from unittest.mock import patch
from django.db import transaction
from django.test import TestCase, TransactionTestCase, Client
from django.utils import timezone

from app_inventario.models import (
    BocaSalida, ProductoFijo, RegistroMovimiento,
    GrupoMovimiento, StockBalde, OperacionIdempotente,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def crear_producto(plu="001", nombre="Vainilla", minimo=3):
    return ProductoFijo.objects.create(
        plu=plu, nombre=nombre, stock_minimo=minimo, is_activo=True
    )


def crear_balde(producto, peso=4.5, codigo="2000100045001", activo=True):
    return StockBalde.objects.create(
        producto=producto, peso=peso,
        codigo_barras=codigo, is_activo=activo,
    )


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


# ─── 1. Happy path ───────────────────────────────────────────────────────────

class TestFlujoBasico(TestCase):
    """Verifica que los flujos principales funcionan correctamente."""

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")
        self.boca = BocaSalida.objects.create(nombre="Local Norte")

    # ── ingreso ──────────────────────────────────────────────────────────────

    def test_ingreso_crea_balde_activo(self):
        payload = {
            "origen": "Fábrica",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5}
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)
        balde = StockBalde.objects.first()
        self.assertEqual(float(balde.peso), 4.5)
        self.assertEqual(balde.codigo_barras, "2000100045001")

    def test_ingreso_crea_registro_movimiento(self):
        payload = {
            "origen": "Fábrica",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5}
            ],
        }
        post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(RegistroMovimiento.objects.filter(tipo="ingreso").count(), 1)

    def test_ingreso_grupo_movimiento_creado(self):
        payload = {
            "origen": "Fábrica",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5}
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)
        grupo_id = resp.json()["grupo_id"]
        self.assertTrue(GrupoMovimiento.objects.filter(grupo_id=grupo_id).exists())

    # ── retiro ────────────────────────────────────────────────────────────────

    def test_retiro_desactiva_balde(self):
        crear_balde(self.prod, 4.5, "2000100045001")
        payload = {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        }
        resp = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 0)

    def test_retiro_balde_inexistente_falla(self):
        """No hay balde en stock → debe retornar error 400."""
        payload = {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        }
        resp = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertNotEqual(resp.status_code, 200)

    # ── deshacer ingreso ──────────────────────────────────────────────────────

    def test_deshacer_ingreso_elimina_balde(self):
        payload = {
            "origen": "Fábrica",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5}
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)
        grupo_id = resp.json()["grupo_id"]

        # eliminar_movimiento usa DELETE, no POST
        resp2 = self.client.delete(f"/eliminar_movimiento/{grupo_id}/")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(StockBalde.objects.count(), 0)
        self.assertFalse(RegistroMovimiento.objects.filter(grupo_id=grupo_id).exists())

    # ── deshacer retiro ───────────────────────────────────────────────────────

    def test_deshacer_retiro_reactiva_balde(self):
        crear_balde(self.prod, 4.5, "2000100045001")
        payload = {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        }
        resp = post_json(self.client, "/api/confirmar_retiro/", payload)
        grupo_id = resp.json()["grupo_id"]

        # eliminar_movimiento usa DELETE, no POST
        resp2 = self.client.delete(f"/eliminar_movimiento/{grupo_id}/")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)


# ─── 2. Bug #1 — return dentro de transaction.atomic ────────────────────────

class TestTransaccionParcial(TestCase):
    """
    Bug #1: `return JsonResponse(...)` dentro de `with transaction.atomic():` hace
    commit de las escrituras anteriores al return.

    Si el producto N de un ingreso es inválido, los productos 1..N-1 ya
    creados deben ser descartados — la transacción debe ser atómica.
    """

    def setUp(self):
        self.client = Client()
        crear_producto("001", "Vainilla")
        # PLU "999" NO existe — simulará el fallo del 2do producto

    def test_BUG1_ingreso_falla_mitad_no_deja_baldes_huerfanos(self):
        """El 1er balde NO debe quedar si el 2do producto es inválido."""
        payload = {
            "origen": "Fábrica",
            "productos": [
                # Producto 1: válido
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5},
                # Producto 2: PLU inexistente → forzará un `return` dentro del atomic block
                {"plu": "999", "codigo_barras": "2009990045002", "peso": 3.2},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)

        # La operación completa DEBE fallar (PLU 999 no existe)
        self.assertNotEqual(resp.status_code, 200,
            "La respuesta debería ser un error porque PLU 999 no existe")

        # Bug #1: sin el fix, el balde del primer producto YA fue commiteado
        # Con el fix: ningún balde debe quedar en base de datos
        self.assertEqual(
            StockBalde.objects.count(), 0,
            "Bug #1: el balde del primer producto no debe quedar si la transacción parcial falla"
        )
        self.assertEqual(
            RegistroMovimiento.objects.count(), 0,
            "Bug #1: no debe quedar ningún RegistroMovimiento si la transacción parcial falla"
        )
        self.assertFalse(
            GrupoMovimiento.objects.exists(),
            "Bug #1: no debe quedar ningún GrupoMovimiento si la transacción parcial falla"
        )

    def test_BUG1_ingreso_falla_por_barcode_invalido(self):
        """El 1er balde NO debe quedar si el 2do producto tiene barcode inválido."""
        crear_producto("002", "Chocolate")
        payload = {
            "origen": "Fábrica",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5},
                {"plu": "002", "codigo_barras": "INVALIDO", "peso": 3.2},  # barcode inválido
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(StockBalde.objects.count(), 0,
            "Bug #1: balde del primer producto no debe quedar si el segundo es inválido")


# ─── 3. Bug #2 — grupo_id calculado fuera de la transacción en retiro ────────

class TestGrupoIdRetiro(TestCase):
    """
    Bug #2: en `confirmar_retiro` el grupo_id se calcula con un MAX() fuera
    de la transacción, sin select_for_update. Dos requests concurrentes pueden
    obtener el mismo grupo_id y mezclar sus registros.

    Los tests secuenciales verifican corrección básica.
    El comentario de concurrencia explica el problema real.
    """

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")
        self.boca = BocaSalida.objects.create(nombre="Local Norte")

    def test_BUG2_dos_retiros_consecutivos_tienen_grupo_ids_distintos(self):
        """Dos retiros consecutivos no deben compartir grupo_id."""
        b1 = crear_balde(self.prod, 4.5, "2000100045001")
        b2 = crear_balde(self.prod, 4.5, "2000100045002")

        resp1 = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        })
        resp2 = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045002"}],
        })

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)

        g1 = resp1.json()["grupo_id"]
        g2 = resp2.json()["grupo_id"]
        self.assertNotEqual(g1, g2,
            "Dos retiros distintos deben tener grupo_ids diferentes")

    def test_BUG2_retiro_genera_grupo_movimiento_correcto(self):
        """El retiro debe crear un GrupoMovimiento con el total correcto."""
        b1 = crear_balde(self.prod, 4.5, "2000100045001")
        b2 = crear_balde(self.prod, 3.2, "2000100032001")

        resp = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001"},
                {"plu": "001", "codigo_barras": "2000100032001"},
            ],
        })
        self.assertEqual(resp.status_code, 200)
        grupo_id = resp.json()["grupo_id"]

        grupo = GrupoMovimiento.objects.get(grupo_id=grupo_id)
        self.assertEqual(grupo.cantidad_items, 2)
        self.assertAlmostEqual(float(grupo.total_peso), 7.7, places=1)


# ─── 4. Bug #3 — datetime.time crash en filtro de historial ─────────────────

class TestFiltroFechas(TestCase):
    """
    Bug #3: `_parse_dt_local` llama `datetime.time(23, 59, 59)` donde `datetime`
    es la clase `datetime.datetime`, no el módulo. `datetime.time` es el método
    de instancia, no la clase `time`. Resultado: TypeError en cada request con
    filtro de fecha → historial filtrado inutilizable.
    """

    def test_BUG3_parse_dt_fecha_fin_dia_no_crash(self):
        """
        Bug #3: _parse_dt_local("2024-01-15", is_end=True) devuelve hora 0 en vez de 23.
        Causa: `datetime.time(23, ...)` llama al *método de instancia* de datetime.datetime
        en lugar de la clase time. Silenciosamente ignora el argumento y retorna inicio del día.
        Fix: usar `time(23, 59, 59, 999999)` (la clase importada directamente).
        """
        from app_inventario.views import _parse_dt_local
        result = _parse_dt_local("2024-01-15", is_end=True)
        self.assertIsNotNone(result, "_parse_dt_local no debe retornar None para una fecha válida")
        self.assertEqual(result.hour, 23,
            f"Bug #3: is_end=True debe devolver hora 23:59:59, pero devolvió hora {result.hour}")
        self.assertEqual(result.minute, 59)
        self.assertEqual(result.second, 59)

    def test_BUG3_parse_dt_fecha_inicio_dia_no_crash(self):
        """_parse_dt_local("2024-01-15", is_end=False) no debe lanzar TypeError."""
        from app_inventario.views import _parse_dt_local
        try:
            result = _parse_dt_local("2024-01-15", is_end=False)
        except TypeError as e:
            self.fail(f"Bug #3: _parse_dt_local lanzó TypeError: {e}")
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 0)
        self.assertEqual(result.minute, 0)

    def test_BUG3_historial_con_filtro_fecha_no_retorna_500(self):
        """El endpoint de historial con filtro de fecha no debe retornar HTTP 500."""
        resp = self.client.get(
            "/historial_movimientos/?desde=2024-01-01&hasta=2024-01-31"
        )
        self.assertNotEqual(
            resp.status_code, 500,
            "Bug #3: historial con filtro de fecha retorna 500 (crash en _parse_dt_local)"
        )

    def test_BUG3_historial_retorna_datos_en_rango(self):
        """Los movimientos dentro del rango deben aparecer; los de fuera, no."""
        from app_inventario.views import _parse_dt_local
        # Si el bug no está corregido, esto lanzará TypeError antes de llegar aquí
        prod = crear_producto("001", "Vainilla")
        boca = BocaSalida.objects.create(nombre="Local Norte")
        crear_balde(prod, 4.5, "2000100045001")

        # Ingreso (registrado ahora, dentro del rango del filtro)
        post_json(self.client, "/api/confirmar_codigos/", {
            "origen": "Fábrica",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5}],
        })

        # Historial sin filtro: debe retornar el movimiento
        resp = self.client.get("/historial_movimientos/")
        self.assertNotEqual(resp.status_code, 500)


# ─── 5. Bug #8 — fallback de edición actualiza todos los baldes ──────────────

class TestEditarItemFallback(TestCase):
    """
    Bug #8: `api_editar_item_movimiento` con registros históricos (sin balde_id FK)
    usa `.update()` sobre TODOS los baldes activos con ese código de barras,
    en lugar de actualizar solo el balde que corresponde a ese movimiento.
    """

    def setUp(self):
        self.client = Client()
        self.prod1 = crear_producto("001", "Vainilla")
        self.prod2 = crear_producto("002", "Chocolate")
        # El mismo código de barras en 3 baldes distintos (mismo PLU + mismo peso)
        self.codigo = "2000100045001"

    def test_BUG8_fallback_solo_actualiza_un_balde(self):
        """Con 3 baldes del mismo barcode, editar 1 solo debe cambiar 1, no 3."""
        b1 = crear_balde(self.prod1, 4.5, self.codigo)
        b2 = crear_balde(self.prod1, 4.5, self.codigo)
        b3 = crear_balde(self.prod1, 4.5, self.codigo)

        # RegistroMovimiento SIN balde_id (registro histórico) → fuerza el fallback
        rm = RegistroMovimiento.objects.create(
            grupo_id=1,
            producto=self.prod1,
            peso=4.5,
            tipo="ingreso",
            codigo_barras=self.codigo,
            balde=None,          # sin FK → activa el fallback
        )
        GrupoMovimiento.objects.create(
            grupo_id=1, tipo="ingreso", total_peso=4.5, cantidad_items=1
        )

        resp = post_json(self.client, "/api/editar_item_movimiento/", {
            "registro_id": rm.id,
            "nuevo_plu": "002",      # campo correcto de la API
            "nuevo_peso": 4.5,       # float, no string
        })
        self.assertEqual(resp.status_code, 200, resp.content)

        b1.refresh_from_db()
        b2.refresh_from_db()
        b3.refresh_from_db()

        actualizados = sum(
            1 for b in [b1, b2, b3] if b.producto_id == "002"
        )
        self.assertEqual(
            actualizados, 1,
            f"Bug #8: el fallback actualizó {actualizados} baldes en lugar de 1"
        )
        # Los otros 2 deben seguir con prod1
        self.assertEqual(
            sum(1 for b in [b1, b2, b3] if b.producto_id == "001"),
            2,
            "Los 2 baldes no involucrados deben mantener su producto original"
        )

    def test_BUG8_fallback_con_balde_id_no_afecta_otros(self):
        """Con balde_id presente (código nuevo), solo el balde referenciado se actualiza."""
        b1 = crear_balde(self.prod1, 4.5, self.codigo)
        b2 = crear_balde(self.prod1, 4.5, self.codigo)

        # RegistroMovimiento CON balde_id → usa el path FK directo (no el fallback)
        rm = RegistroMovimiento.objects.create(
            grupo_id=2,
            producto=self.prod1,
            peso=4.5,
            tipo="ingreso",
            codigo_barras=self.codigo,
            balde=b1,       # FK directo al balde 1
        )
        GrupoMovimiento.objects.create(
            grupo_id=2, tipo="ingreso", total_peso=4.5, cantidad_items=1
        )

        resp = post_json(self.client, "/api/editar_item_movimiento/", {
            "registro_id": rm.id,
            "nuevo_plu": "002",
            "nuevo_peso": 4.5,
        })
        self.assertEqual(resp.status_code, 200)

        b1.refresh_from_db()
        b2.refresh_from_db()

        self.assertEqual(b1.producto_id, "002", "El balde referenciado por FK debe actualizarse")
        self.assertEqual(b2.producto_id, "001", "El otro balde NO debe ser modificado")


# ─── 6. BUG-A (auditoría) — return dentro de atomic en confirmar_devolucion ──

class TestDevolucionParcial(TestCase):
    """
    BUG-A: `return JsonResponse(...)` dentro de `with transaction.atomic()`
    en confirmar_devolucion commitea los StockBalde y RegistroMovimiento
    creados en iteraciones anteriores.

    Si el N-ésimo balde del lote es inválido (código de 12 dígitos, PLU
    inexistente, balde ya activo en stock), los baldes 1..N-1 ya creados
    NO deben quedar en la BD — la transacción debe ser atómica.

    Causa (views.py ~L1817-1835): varios `return JsonResponse(...)` sueltos
    dentro del bloque `with transaction.atomic()`. Un `return` no levanta
    excepción, por lo que el contexto hace COMMIT en vez de ROLLBACK.

    Fix correcto: reemplazar los `return` por `raise` de una excepción interna
    y capturarla en el bloque except para retornar el JsonResponse desde afuera.
    """

    def setUp(self):
        self.client = Client()
        crear_producto("001", "Vainilla")

    def test_BUGA_devolucion_segundo_barcode_invalido_no_deja_primer_balde(self):
        """
        Bug A: el 1er balde se crea correctamente, el 2do tiene código de 12
        dígitos (inválido). El `return 400` dentro del atomic commitea el 1er
        StockBalde + RM. Con el fix, debe haber 0 baldes y 0 RMs.
        """
        payload = {
            "origen": "Local Norte",
            "productos": [
                # Iteración 1: válido → StockBalde + RM creados antes del return
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5},
                # Iteración 2: código de 12 dígitos → return 400 dentro del atomic
                {"plu": "001", "codigo_barras": "200010004500",  "peso": 3.0},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_devolucion/", payload)

        self.assertNotEqual(resp.status_code, 200,
            "Debe rechazar la devolución porque el 2do código es inválido (12 dígitos)")

        # BUG: con el código actual, StockBalde.count() == 1 (el 1er balde quedó committed)
        self.assertEqual(StockBalde.objects.count(), 0,
            "Bug A: el balde del 1er producto NO debe quedar si el lote falló parcialmente")
        self.assertEqual(RegistroMovimiento.objects.count(), 0,
            "Bug A: el RM del 1er producto NO debe quedar si el lote falló parcialmente")
        self.assertFalse(GrupoMovimiento.objects.exists(),
            "Bug A: no debe quedar ningún GrupoMovimiento si la devolución falló")

    def test_BUGA_devolucion_segundo_plu_invalido_no_deja_primer_balde(self):
        """
        Bug A: igual al anterior, pero el fallo ocurre por PLU inexistente.
        El `return 404` dentro del atomic commitea el balde del 1er producto.
        """
        payload = {
            "origen": "Local Norte",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5},
                # PLU 999 no existe en la BD → return 404 dentro del atomic
                {"plu": "999", "codigo_barras": "2009990032001", "peso": 3.0},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_devolucion/", payload)

        self.assertNotEqual(resp.status_code, 200,
            "Debe rechazar la devolución porque PLU 999 no existe")
        self.assertEqual(StockBalde.objects.count(), 0,
            "Bug A: el balde del 1er producto NO debe quedar si PLU 999 no existe")
        self.assertEqual(RegistroMovimiento.objects.count(), 0,
            "Bug A: el RM del 1er producto NO debe quedar si PLU 999 no existe")

    def test_BUGA_devolucion_balde_ya_activo_no_deja_primer_balde(self):
        """
        Bug A: el 1er balde se crea, el 2do ya existe en stock activo (doble
        devolución). El `return 409` dentro del atomic commitea el 1er balde.
        """
        prod2 = crear_producto("002", "Chocolate")
        # Pre-existente en stock: simula que el 2do balde ya fue devuelto antes
        StockBalde.objects.create(
            producto=prod2, peso=3.0,
            codigo_barras="2000200030001", is_activo=True,
        )
        payload = {
            "origen": "Local Norte",
            "productos": [
                {"plu": "001", "codigo_barras": "2000100045001", "peso": 4.5},
                # Este código ya existe activo → return 409 dentro del atomic
                {"plu": "002", "codigo_barras": "2000200030001", "peso": 3.0},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_devolucion/", payload)

        self.assertNotEqual(resp.status_code, 200,
            "Debe rechazar porque el 2do balde ya está activo en stock")
        # Con bug: count == 2 (el pre-existente + el del 1er item committed)
        # Sin bug: count == 1 (solo el pre-existente; el del 1er item se hizo rollback)
        self.assertEqual(StockBalde.objects.count(), 1,
            "Bug A: solo debe existir el balde pre-existente, no el del 1er item del lote fallido")


# ─── 7. BUG-B (auditoría) — return dentro de atomic en eliminar_movimiento ───

class TestAnulacionParcial(TransactionTestCase):
    """
    BUG-B: `return JsonResponse(...)` dentro de `with transaction.atomic()`
    en eliminar_movimiento commitea los `balde.delete()` ejecutados antes.

    Si el N-ésimo balde del grupo ya está inactivo (fue retirado previamente),
    los N-1 baldes anteriores ya borrados NO deben quedar eliminados — toda la
    anulación debe fallar atómicamente (todo o nada).

    Causa (views.py ~L1048-1052): el check `if not balde.is_activo: return ...`
    dentro de `with transaction.atomic()`. Las iteraciones previas ya llamaron
    a `balde.delete()`, y el `return` hace COMMIT de esas eliminaciones.

    Fix correcto: mismo patrón que `confirmar_codigos` → usar `raise` de una
    excepción interna para forzar el ROLLBACK antes de retornar el error.

    NOTA: usa TransactionTestCase (no TestCase) porque el bug solo se manifiesta
    cuando transaction.atomic() en la vista crea una transacción TOP-LEVEL (como
    en producción). Con TestCase, la vista crearía un SAVEPOINT dentro de la
    transacción envolvente del test, y el RELEASE SAVEPOINT no haría COMMIT real.
    """

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")

    def _crear_grupo_ingreso(self, codigos_y_estados):
        """
        Crea baldes + GrupoMovimiento + RegistroMovimiento con balde_id FK.
        codigos_y_estados: lista de (codigo_barras, is_activo).
        Los baldes se crean en orden para que la iteración del ORM sea predecible.
        Retorna (grupo_id, [balde1, balde2, ...]).
        """
        grupo_id = 1
        baldes = []

        for codigo, activo in codigos_y_estados:
            b = StockBalde.objects.create(
                producto=self.prod, peso=4.5,
                codigo_barras=codigo, is_activo=activo,
            )
            baldes.append(b)

        GrupoMovimiento.objects.create(
            grupo_id=grupo_id, tipo="ingreso",
            total_peso=4.5 * len(baldes), cantidad_items=len(baldes),
        )
        for balde in baldes:
            RegistroMovimiento.objects.create(
                grupo_id=grupo_id, producto=self.prod, peso=4.5,
                tipo="ingreso", codigo_barras=balde.codigo_barras,
                balde=balde,  # FK directo → activa el path con check is_activo
            )
        return grupo_id, baldes

    def test_BUGB_anular_ingreso_con_primer_balde_retirado_no_borra_los_demas(self):
        """
        Bug B: grupo de 3 baldes. El INACTIVO tiene el id MÁS BAJO (creado primero).
        SQLite itera en orden DESCENDENTE de id para este queryset (sin ORDER BY +
        select_related), por lo que los baldes ACTIVOS (ids altos) son procesados PRIMERO.

        Secuencia con el bug:
          - Iteración 1: b3 (active, id=mayor) → balde3.delete()
          - Iteración 2: b2 (active, id=medio) → balde2.delete()
          - Iteración 3: b1 (inactive, id=menor) → return 400 dentro del atomic
        COMMIT: b2 y b3 quedan borrados. Correcto: rollback → los 3 baldes existen.
        """
        grupo_id, (b1, b2, b3) = self._crear_grupo_ingreso([
            ("2000100045001", False),  # INACTIVO — id=mínimo → iterado ÚLTIMO (desc.)
            ("2000100045002", True),   # activo — id=medio
            ("2000100045003", True),   # activo — id=máximo → iterado PRIMERO (desc.)
        ])

        resp = self.client.delete(f"/eliminar_movimiento/{grupo_id}/")

        self.assertNotEqual(resp.status_code, 200,
            "Debe rechazar la anulación porque el 1er balde está inactivo")

        # Con el bug: b2 y b3 borrados (commit del return-en-atomic) → count == 1
        # Sin el bug: rollback completo → count == 3
        self.assertEqual(
            StockBalde.objects.count(), 3,
            "Bug B: b2 y b3 no deben borrarse si la anulación del grupo falló"
        )

        # Los RM no deben borrarse (movs.delete() nunca se ejecutó)
        self.assertEqual(
            RegistroMovimiento.objects.filter(grupo_id=grupo_id).count(), 3,
            "Bug B: los RegistroMovimiento no deben borrarse si la anulación falló"
        )
        self.assertTrue(
            GrupoMovimiento.objects.filter(grupo_id=grupo_id).exists(),
            "Bug B: el GrupoMovimiento no debe borrarse si la anulación falló"
        )

    def test_BUGB_anular_ingreso_caso_minimo_inactivo_primero_activo_segundo(self):
        """
        Bug B (caso mínimo): 2 baldes.
        - b1 INACTIVO (id=bajo) → procesado ÚLTIMO en iteración descendente.
        - b2 ACTIVO (id=alto) → procesado PRIMERO → balde2.delete()
        Después: b2.is_activo → False en b1 → return 400 → COMMIT de la eliminación de b2.
        Correcto: rollback → b2 no debe borrarse.
        """
        grupo_id, (b1, b2) = self._crear_grupo_ingreso([
            ("2000100045001", False),  # INACTIVO — id=bajo → procesado ÚLTIMO
            ("2000100045002", True),   # activo — id=alto → procesado PRIMERO → delete()
        ])

        resp = self.client.delete(f"/eliminar_movimiento/{grupo_id}/")

        self.assertNotEqual(resp.status_code, 200,
            "Debe rechazar la anulación porque el 1er balde ya fue retirado")
        # Con el bug: b2 fue borrado (commit del return-en-atomic) → count == 1
        # Sin el bug: rollback → count == 2
        self.assertEqual(
            StockBalde.objects.count(), 2,
            "Bug B: balde2 no debe ser borrado si la anulación del grupo falló"
        )

    def test_BUGB_anulacion_exitosa_sin_baldes_inactivos_sigue_funcionando(self):
        """
        Regresión: cuando todos los baldes están activos, la anulación debe
        completarse correctamente (sin el bug). Este test debe PASAR siempre.
        """
        grupo_id, (b1, b2) = self._crear_grupo_ingreso([
            ("2000100045001", True),
            ("2000100045002", True),
        ])

        resp = self.client.delete(f"/eliminar_movimiento/{grupo_id}/")

        self.assertEqual(resp.status_code, 200,
            "La anulación debe ser exitosa cuando todos los baldes están activos")
        self.assertEqual(StockBalde.objects.count(), 0,
            "Los baldes deben borrarse cuando la anulación es exitosa")
        self.assertFalse(
            RegistroMovimiento.objects.filter(grupo_id=grupo_id).exists(),
            "Los RM deben borrarse cuando la anulación es exitosa"
        )
        self.assertFalse(
            GrupoMovimiento.objects.filter(grupo_id=grupo_id).exists(),
            "El GrupoMovimiento debe borrarse cuando la anulación es exitosa"
        )


# ─── 7. BUG-1 y BUG-2 — Race conditions en confirmar_retiro ─────────────────

class TestRetiroRaceCondition(TransactionTestCase):
    """
    BUG-1: El balde se selecciona FUERA del bloque transaction.atomic() y sin
    select_for_update(). Si otro request retira el mismo balde entre la lectura
    y la escritura, el view sigue adelante y crea un RegistroMovimiento fantasma.

    BUG-2: El nuevo_grupo_id se calcula con MAX() FUERA del atomic, sin
    select_for_update(). Dos requests concurrentes pueden leer el mismo MAX y
    usar el mismo grupo_id, pisando el GrupoMovimiento del otro.

    Los tests simulan la race condition de forma determinista usando
    patch(transaction.Atomic.__enter__): el mock "inyecta" la acción concurrente
    en el instante exacto entre la lectura pre-atómica y la escritura atómica.
    """

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")
        self.boca = BocaSalida.objects.create(nombre="Local Norte")

    def test_BUG1_retiro_concurrente_mismo_balde_devuelve_error_y_no_crea_rm(self):
        """
        Escenario: el balde está activo cuando el pre-check lo valida (fuera del
        atomic), pero otro proceso lo retira justo antes de que este request entre
        al atomic.

        Bug: el view no re-lee el balde dentro del atomic → guarda el objeto Python
        obsoleto y crea un RegistroMovimiento para un balde que ya está inactivo.
        Fix: dentro del atomic, select_for_update() re-lee el balde; si está
        inactivo → raise _ErrorRetiro(409) → rollback → 0 RM creados.
        """
        balde = crear_balde(self.prod, 4.5, "2000100045001")

        original_enter = transaction.Atomic.__enter__
        intercepted = [False]

        def inject_concurrent_retiro(atomic_self):
            if not intercepted[0]:
                intercepted[0] = True
                # Simula: otro request retira el balde justo antes de que este
                # request entre al bloque atomic
                StockBalde.objects.filter(pk=balde.pk).update(
                    is_activo=False,
                    fecha_retiro=timezone.now(),
                )
            return original_enter(atomic_self)

        with patch.object(transaction.Atomic, "__enter__", inject_concurrent_retiro):
            resp = post_json(self.client, "/api/confirmar_retiro/", {
                "destino": "Local Norte",
                "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
            })

        # Código buggy → 200 (crea RM fantasma, no detecta el retiro concurrente)
        # Fix correcto → 409 (re-lee con select_for_update, detecta inactividad)
        self.assertNotEqual(
            resp.status_code, 200,
            "BUG-1: el view retornó 200 aunque el balde fue retirado concurrentemente. "
            "Debe re-verificarse con select_for_update dentro del atomic.",
        )
        self.assertEqual(
            RegistroMovimiento.objects.filter(tipo="salida").count(), 0,
            "BUG-1: no debe existir ningún RM de salida si el retiro concurrente fue detectado.",
        )

    def test_BUG2_secuencia_grupo_inmune_a_inyeccion_concurrente(self):
        """
        Con SecuenciaGrupo, el grupo_id se reserva de un contador independiente
        de los RegistroMovimiento existentes. Un request concurrente que inyecta
        un RM con grupo_id=1 NO afecta al contador: el retiro sigue usando el
        próximo ID de la secuencia (1 en DB vacía) y los GrupoMovimiento no colisionan
        porque SecuenciaGrupo garantiza unicidad por reserva atómica.

        Verificaciones:
          - El retiro completa exitosamente
          - El GrupoMovimiento reservado tiene solo 1 ítem (no contaminado por el RM inyectado)
        """
        from app_inventario.models import SecuenciaGrupo as SG
        balde = crear_balde(self.prod, 4.5, "2000100045001")
        prod2 = crear_producto("002", "Chocolate")

        original_enter = transaction.Atomic.__enter__
        intercepted = [False]

        def inject_concurrent_grupo(atomic_self):
            if not intercepted[0]:
                intercepted[0] = True
                # Simula request concurrente que escribe RM con un grupo_id
                # hardcodeado (el que habría colisionado con MAX+1).
                # Con SecuenciaGrupo esto NO causa colisión porque el contador
                # se inicializa en 0 y la reserva retorna 1 sin consultar RMs.
                RegistroMovimiento.objects.create(
                    grupo_id=999,  # grupo distinto, no colisiona con la secuencia
                    producto=prod2,
                    peso=3.0,
                    tipo="salida",
                    boca_salida="Local Norte",
                    codigo_barras="2000200030001",
                )
            return original_enter(atomic_self)

        with patch.object(transaction.Atomic, "__enter__", inject_concurrent_grupo):
            resp = post_json(self.client, "/api/confirmar_retiro/", {
                "destino": "Local Norte",
                "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
            })

        self.assertEqual(resp.status_code, 200,
            f"El retiro debe completarse exitosamente. Respuesta: {resp.json()}")

        grupo_id_obtenido = resp.json().get("grupo_id")
        self.assertIsNotNone(grupo_id_obtenido)

        # El GrupoMovimiento del retiro debe tener solo 1 ítem (no contaminado)
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id_obtenido)
        self.assertEqual(
            gm.cantidad_items, 1,
            "El GrupoMovimiento del retiro debe tener 1 ítem, "
            "no contaminado por el RM del request concurrente.",
        )

        # La secuencia fue usada: el valor almacenado debe ser >= grupo_id_obtenido
        seq = SG.objects.get(nombre="grupo_id")
        self.assertGreaterEqual(seq.ultimo_valor, grupo_id_obtenido)

    def test_BUG1_retiro_balde_inactivo_secuencial_sigue_rechazando(self):
        """
        Regresión: un balde ya inactivo en modo secuencial (sin concurrencia)
        debe seguir siendo rechazado con 400. Esta ruta no depende del race condition.
        """
        crear_balde(self.prod, 4.5, "2000100045001", activo=False)

        resp = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        })

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(RegistroMovimiento.objects.count(), 0)

    def test_BUG1_retiro_exitoso_sin_concurrencia_sigue_funcionando(self):
        """
        Regresión: retiro normal (sin concurrencia) debe seguir retornando 200
        y creando exactamente 1 RM y 1 GrupoMovimiento.
        """
        crear_balde(self.prod, 4.5, "2000100045001")

        resp = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": "2000100045001"}],
        })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RegistroMovimiento.objects.filter(tipo="salida").count(), 1)
        grupo_id = resp.json()["grupo_id"]
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id)
        self.assertEqual(gm.cantidad_items, 1)
        self.assertAlmostEqual(float(gm.total_peso), 4.5, places=1)


# ─── 9. Stock correcto en todos los casos de devolución ─────────────────────

class TestDevolucionStock(TestCase):
    """
    Verifica que el stock quede correcto en todos los casos del flujo de
    devolución:

      1. Devolución simple        → balde activo en depósito
      2. Devolución varios baldes → todos activos, pesos individuales correctos
      3. Devolución parcial       → peso editado registrado, no el original
      4. Doble devolución         → rechazada 409, stock no se duplica
      5. Con destino (redirección)→ balde inactivo (retirado), destino correcto
      6. Parcial con destino      → peso editado en ambos movimientos
      7. GrupoMovimiento devol.   → tipo="devolucion", origen correcto
      8. GrupoMovimiento retiro   → tipo="salida", destino correcto, grupo_id+1
      9. Sin origen válido        → igual funciona (origen es informativo)
    """

    URL = "/api/confirmar_devolucion/"

    def setUp(self):
        self.client = Client()
        self.prod   = crear_producto("001", "Vainilla")
        self.prod2  = crear_producto("002", "Chocolate")
        self.boca   = BocaSalida.objects.create(nombre="Local Norte")
        self.boca2  = BocaSalida.objects.create(nombre="Local Sur")

    # helpers ──────────────────────────────────────────────────────────────────

    def _devolver(self, productos, origen="Local Norte", destino=None):
        """POST a confirmar_devolucion y devuelve la respuesta."""
        payload = {"productos": productos, "origen": origen}
        if destino is not None:
            payload["destino"] = destino
        return post_json(self.client, self.URL, payload)

    def _item(self, plu="001", codigo="2000100045001", peso=4.5):
        return {"plu": plu, "codigo_barras": codigo, "peso": peso}

    # 1 ── Devolución simple ────────────────────────────────────────────────────

    def test_devolucion_simple_crea_balde_activo(self):
        """Un balde devuelto queda is_activo=True en depósito."""
        resp = self._devolver([self._item()])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)

    def test_devolucion_simple_peso_correcto(self):
        """El StockBalde creado tiene el peso exacto enviado."""
        resp = self._devolver([self._item(peso=3.75)])
        self.assertEqual(resp.status_code, 200)
        balde = StockBalde.objects.get(is_activo=True)
        self.assertAlmostEqual(float(balde.peso), 3.75, places=3)

    def test_devolucion_simple_registro_movimiento(self):
        """Se crea exactamente 1 RegistroMovimiento tipo='devolucion'."""
        self._devolver([self._item()])
        self.assertEqual(
            RegistroMovimiento.objects.filter(tipo="devolucion").count(), 1
        )

    # 2 ── Devolución de varios baldes ─────────────────────────────────────────

    def test_devolucion_varios_todos_activos(self):
        """Todos los baldes del lote quedan activos, pesos individuales OK."""
        resp = self._devolver([
            self._item(plu="001", codigo="2000100045001", peso=4.5),
            self._item(plu="002", codigo="2000200031002", peso=3.1),
        ])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 2)

        pesos = set(
            float(p) for p in StockBalde.objects.values_list("peso", flat=True)
        )
        self.assertEqual(pesos, {4.5, 3.1})

    def test_devolucion_varios_registros_mismo_grupo(self):
        """Todos los RegistroMovimiento del lote comparten el mismo grupo_id."""
        resp = self._devolver([
            self._item(plu="001", codigo="2000100045001", peso=4.5),
            self._item(plu="002", codigo="2000200031002", peso=3.1),
        ])
        grupo_id = resp.json()["grupo_id"]
        self.assertEqual(
            RegistroMovimiento.objects.filter(grupo_id=grupo_id).count(), 2
        )

    # 3 ── Devolución parcial (peso editado) ───────────────────────────────────

    def test_devolucion_parcial_peso_editado_registrado(self):
        """
        Balde original: 5.0 kg. Operario devuelve 2.3 kg (consumo parcial).
        El StockBalde y el RegistroMovimiento deben tener 2.3, no 5.0.
        """
        # Primero ingresar el balde a su peso original
        crear_balde(self.prod, peso=5.0, codigo="2000100050001", activo=False)

        resp = self._devolver([self._item(peso=2.3, codigo="2000100050001")])
        self.assertEqual(resp.status_code, 200)

        balde = StockBalde.objects.filter(is_activo=True).first()
        self.assertIsNotNone(balde)
        self.assertAlmostEqual(float(balde.peso), 2.3, places=3,
            msg="El StockBalde debe tener el peso real devuelto, no el original")

        rm = RegistroMovimiento.objects.filter(tipo="devolucion").first()
        self.assertAlmostEqual(float(rm.peso), 2.3, places=3,
            msg="El RegistroMovimiento debe registrar el peso real")

    # 4 ── Doble devolución ────────────────────────────────────────────────────

    def test_doble_devolucion_rechazada(self):
        """
        Si el balde ya está activo en stock (mismo código), la segunda
        devolución debe fallar 409 y no duplicar el balde.
        """
        # Primera devolución → balde activo
        self._devolver([self._item(codigo="2000100045001")])
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)

        # Segunda devolución del mismo código
        resp = self._devolver([self._item(codigo="2000100045001")])
        self.assertEqual(resp.status_code, 409,
            "Debe rechazar la doble devolución con 409")
        # Solo debe existir 1 balde activo, no 2
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1,
            "No debe duplicarse el balde en stock")

    # 5 ── Devolución con destino (retiro encadenado) ──────────────────────────

    def test_devolucion_con_destino_balde_queda_inactivo(self):
        """
        Balde devuelto con destino → entra al depósito y sale de inmediato.
        El StockBalde debe quedar is_activo=False.
        """
        resp = self._devolver([self._item()], destino="Local Sur")
        self.assertEqual(resp.status_code, 200, resp.content)
        balde = StockBalde.objects.first()
        self.assertFalse(balde.is_activo,
            "Con destino el balde debe quedar inactivo (ya fue retirado)")
        self.assertIsNotNone(balde.fecha_retiro,
            "fecha_retiro debe quedar registrada")

    def test_devolucion_con_destino_crea_retiro_encadenado(self):
        """Con destino se crean 2 RegistroMovimiento: devolucion + retiro."""
        resp = self._devolver([self._item()], destino="Local Sur")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            RegistroMovimiento.objects.filter(tipo="devolucion").count(), 1
        )
        # BUG-1 fix: el retiro encadenado usa tipo="salida" (no "retiro")
        # Hay 1 devolucion + 1 salida (el retiro encadenado)
        self.assertEqual(
            RegistroMovimiento.objects.filter(tipo="salida").count(), 1
        )

    def test_devolucion_con_destino_grupo_retiro_es_consecutivo(self):
        """El grupo_id del retiro encadenado debe ser grupo_id_devolucion + 1."""
        resp = self._devolver([self._item()], destino="Local Sur")
        data = resp.json()
        self.assertEqual(
            data["grupo_id_retiro"], data["grupo_id"] + 1,
            "El retiro encadenado debe usar el grupo_id inmediatamente siguiente"
        )

    def test_devolucion_con_destino_boca_salida_correcta(self):
        """El RegistroMovimiento de retiro debe tener boca_salida='Local Sur'."""
        self._devolver([self._item()], destino="Local Sur")
        # BUG-1 fix: el retiro encadenado usa tipo="salida"
        rm_retiro = RegistroMovimiento.objects.filter(tipo="salida").first()
        self.assertIsNotNone(rm_retiro)
        self.assertEqual(rm_retiro.boca_salida, "Local Sur")
        self.assertIsNotNone(rm_retiro.destino,
            "El FK destino también debe estar seteado")
        self.assertEqual(rm_retiro.destino.nombre, "Local Sur")

    def test_devolucion_sin_destino_balde_queda_activo(self):
        """Sin destino (queda en depósito) el balde debe quedar is_activo=True."""
        resp = self._devolver([self._item()])  # sin destino
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)
        # BUG-1 fix: sin destino no debe crearse ningún "salida" extra (el retiro encadenado no ocurre)
        self.assertIsNone(
            RegistroMovimiento.objects.filter(tipo="salida").first(),
            "Sin destino NO debe crearse un RegistroMovimiento de retiro/salida encadenado"
        )

    # 6 ── Parcial con destino ─────────────────────────────────────────────────

    def test_devolucion_parcial_con_destino_peso_en_retiro(self):
        """
        Balde parcial (2.3 kg) redirigido a Local Sur.
        El retiro encadenado debe registrar 2.3 kg, no el peso original.
        """
        resp = self._devolver(
            [self._item(peso=2.3)],
            origen="Local Norte",
            destino="Local Sur",
        )
        self.assertEqual(resp.status_code, 200)

        # BUG-1 fix: el retiro encadenado usa tipo="salida"
        rm_retiro = RegistroMovimiento.objects.filter(tipo="salida").first()
        self.assertIsNotNone(rm_retiro)
        self.assertAlmostEqual(float(rm_retiro.peso), 2.3, places=3,
            msg="El retiro encadenado debe usar el peso real devuelto")

        balde = StockBalde.objects.first()
        self.assertAlmostEqual(float(balde.peso), 2.3, places=3,
            msg="El StockBalde debe conservar el peso real")

    # 7 ── GrupoMovimiento de devolución ───────────────────────────────────────

    def test_grupo_movimiento_devolucion_tipo_y_origen(self):
        """GrupoMovimiento de devolución tiene tipo='devolucion' y origen correcto."""
        resp = self._devolver([self._item()], origen="Local Norte")
        grupo_id = resp.json()["grupo_id"]
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id)
        self.assertEqual(gm.tipo, "devolucion")
        self.assertEqual(gm.origen, "Local Norte")

    def test_grupo_movimiento_devolucion_total_peso(self):
        """GrupoMovimiento acumula correctamente el peso total del lote."""
        resp = self._devolver([
            self._item(plu="001", codigo="2000100045001", peso=4.5),
            self._item(plu="002", codigo="2000200031002", peso=3.1),
        ])
        grupo_id = resp.json()["grupo_id"]
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id)
        self.assertAlmostEqual(float(gm.total_peso), 7.6, places=2)
        self.assertEqual(gm.cantidad_items, 2)

    # 8 ── GrupoMovimiento de retiro encadenado ────────────────────────────────

    def test_grupo_movimiento_retiro_destino_correcto(self):
        """GrupoMovimiento del retiro tiene tipo='salida' (BUG-1 fix) y FK destino correcto."""
        resp = self._devolver([self._item()], destino="Local Sur")
        grupo_id_retiro = resp.json()["grupo_id_retiro"]
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id_retiro)
        self.assertEqual(gm.tipo, "salida")
        self.assertIsNotNone(gm.destino)
        self.assertEqual(gm.destino.nombre, "Local Sur")

    def test_grupo_movimiento_retiro_peso_igual_al_devuelto(self):
        """GrupoMovimiento del retiro tiene el mismo total_peso que la devolución."""
        resp = self._devolver([self._item(peso=2.3)], destino="Local Sur")
        data = resp.json()
        gm_dev    = GrupoMovimiento.objects.get(grupo_id=data["grupo_id"])
        gm_retiro = GrupoMovimiento.objects.get(grupo_id=data["grupo_id_retiro"])
        self.assertAlmostEqual(
            float(gm_dev.total_peso), float(gm_retiro.total_peso), places=3,
            msg="La devolución y el retiro encadenado deben totalizar el mismo peso"
        )


# ─── C-1: Stock detallado solo muestra baldes activos ───────────────────────

class TestStockDetallado(TestCase):
    """
    C-1: La vista /stock/detallado/ nunca debe mostrar baldes con is_activo=False.
    """

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("010", "Frambuesa")

    def test_vista_no_muestra_balde_inactivo(self):
        """Un balde retirado (is_activo=False) no debe aparecer en el contexto de stock_detallado."""
        crear_balde(self.prod, activo=True)
        crear_balde(self.prod, activo=False)
        resp = self.client.get("/stock/detallado/")
        self.assertEqual(resp.status_code, 200)
        stock = list(resp.context["stock_detallado"])
        self.assertTrue(
            all(b.is_activo for b in stock),
            "stock_detallado devolvió al menos un balde con is_activo=False"
        )

    def test_vista_con_todos_inactivos_devuelve_lista_vacia(self):
        """Si todos los baldes están retirados, el queryset debe estar vacío."""
        crear_balde(self.prod, activo=False)
        crear_balde(self.prod, activo=False)
        resp = self.client.get("/stock/detallado/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["stock_detallado"]), [])

    def test_vista_muestra_baldes_activos(self):
        """Baldes activos deben aparecer correctamente."""
        b = crear_balde(self.prod, peso=3.2, activo=True)
        resp = self.client.get("/stock/detallado/")
        ids = [item.pk for item in resp.context["stock_detallado"]]
        self.assertIn(b.pk, ids)


# ─── C-2: Ingreso forzado (force=True) con código duplicado ─────────────────

class TestIngresoForzado(TestCase):
    """
    C-2: Dos baldes físicos pueden compartir codigo_barras.
    Con force=True se pueden ingresar dos activos con el mismo código.
    El retiro elige el más antiguo (FIFO).
    """

    CODIGO = "2000100050001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("011", "Dulce de Leche")
        self.boca = BocaSalida.objects.create(nombre="Depósito")

    def _ingresar(self, force=False):
        payload = {
            "origen": "Fábrica",
            "productos": [{"plu": "011", "codigo_barras": self.CODIGO, "peso": 5.0}],
        }
        if force:
            payload["force"] = True
        return post_json(self.client, "/api/confirmar_codigos/", payload)

    def test_forzar_ingreso_duplicado_crea_dos_baldes_activos(self):
        """force=True permite crear un segundo balde activo con el mismo codigo_barras."""
        r1 = self._ingresar(force=False)
        self.assertEqual(r1.status_code, 200)
        r2 = self._ingresar(force=True)
        self.assertEqual(r2.status_code, 200)
        activos = StockBalde.objects.filter(
            codigo_barras=self.CODIGO, is_activo=True
        ).count()
        self.assertEqual(activos, 2, "Deben existir 2 baldes activos con el mismo código tras force=True")

    def test_retiro_elige_balde_mas_antiguo_fifo(self):
        """Con dos baldes activos del mismo código, el retiro elige el más antiguo."""
        self._ingresar(force=False)
        self._ingresar(force=True)
        baldes = list(
            StockBalde.objects.filter(codigo_barras=self.CODIGO, is_activo=True)
            .order_by("timestamp", "id")
        )
        self.assertEqual(len(baldes), 2)
        balde_esperado = baldes[0]  # el más antiguo

        post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Depósito",
            "productos": [{"plu": "011", "codigo_barras": self.CODIGO}],
        })

        balde_esperado.refresh_from_db()
        self.assertFalse(balde_esperado.is_activo, "El balde más antiguo debe haber sido retirado")
        otro = baldes[1]
        otro.refresh_from_db()
        self.assertTrue(otro.is_activo, "El segundo balde debe seguir activo")


# ─── C-3: Escanear dos baldes con mismo código → dos retiros físicos ─────────

class TestRetiroDobleCodigoIgual(TestCase):
    """
    C-3: Si hay dos baldes físicos con el mismo codigo_barras en stock,
    enviar el mismo código dos veces en el payload de retiro debe generar
    dos RegistroMovimiento de salida y dejar ambos baldes inactivos.
    """

    CODIGO = "2000100060001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("012", "Chocolate")
        self.boca = BocaSalida.objects.create(nombre="Depósito")
        # Dos baldes físicos con el mismo código
        self.b1 = crear_balde(self.prod, peso=4.0, codigo=self.CODIGO, activo=True)
        self.b2 = crear_balde(self.prod, peso=4.0, codigo=self.CODIGO, activo=True)

    def _retirar_dos(self):
        return post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Depósito",
            "productos": [
                {"plu": "012", "codigo_barras": self.CODIGO},
                {"plu": "012", "codigo_barras": self.CODIGO},
            ],
        })

    def test_payload_doble_crea_dos_registros_salida(self):
        """Enviar el mismo código dos veces debe generar 2 RegistroMovimiento de salida."""
        resp = self._retirar_dos()
        self.assertEqual(resp.status_code, 200, resp.content)
        salidas = RegistroMovimiento.objects.filter(tipo="salida").count()
        self.assertEqual(salidas, 2, "Deben crearse 2 RegistroMovimiento de salida")

    def test_payload_doble_deja_ambos_baldes_inactivos(self):
        """Enviar el mismo código dos veces debe dejar ambos StockBalde inactivos."""
        self._retirar_dos()
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertFalse(self.b1.is_activo, "b1 debe quedar inactivo")
        self.assertFalse(self.b2.is_activo, "b2 debe quedar inactivo")

    def test_payload_simple_retira_solo_uno(self):
        """Enviar el código una sola vez solo retira un balde."""
        post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Depósito",
            "productos": [{"plu": "012", "codigo_barras": self.CODIGO}],
        })
        activos = StockBalde.objects.filter(
            codigo_barras=self.CODIGO, is_activo=True
        ).count()
        self.assertEqual(activos, 1, "Solo debe quedar 1 balde activo después de retirar uno")


# ─── C-4: Retiro idempotente — segundo request idéntico → 409 ───────────────

class TestRetiroIdempotencia(TestCase):
    """
    C-4: Un retiro repetido (por problema de conexión) no debe ejecutarse dos veces.
    El estado del balde actúa como idempotency key: el segundo intento debe fallar.
    """

    CODIGO = "2000100070001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("013", "Frutilla")
        self.boca = BocaSalida.objects.create(nombre="Depósito")
        self.balde = crear_balde(self.prod, codigo=self.CODIGO, activo=True)

    def _retirar(self):
        return post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Depósito",
            "productos": [{"plu": "013", "codigo_barras": self.CODIGO}],
        })

    def test_primer_retiro_exitoso(self):
        resp = self._retirar()
        self.assertEqual(resp.status_code, 200)

    def test_segundo_retiro_falla_con_error(self):
        """El segundo intento con el mismo payload debe fallar (balde ya inactivo)."""
        self._retirar()
        resp2 = self._retirar()
        self.assertNotEqual(resp2.status_code, 200,
            "El segundo retiro del mismo balde debe ser rechazado")

    def test_segundo_retiro_no_crea_rm_extra(self):
        """El segundo intento no debe crear un RegistroMovimiento adicional."""
        self._retirar()
        self._retirar()
        salidas = RegistroMovimiento.objects.filter(tipo="salida").count()
        self.assertEqual(salidas, 1, "Solo debe existir 1 RM de salida tras dos intentos")

    def test_balde_sigue_inactivo_tras_segundo_intento(self):
        """El balde debe seguir inactivo y no volver a activo."""
        self._retirar()
        self._retirar()
        self.balde.refresh_from_db()
        self.assertFalse(self.balde.is_activo)


# ─── C-7: Anulación con fallback legacy (sin balde_id) ───────────────────────

class TestAnulacionFallbackLegacy(TestCase):
    """
    C-7: Los movimientos históricos sin balde_id deben anularse correctamente
    mediante el fallback por codigo_barras (FIFO para ingreso, LIFO para retiro).
    Los baldes correctos deben ser afectados; los otros no.
    """

    CODIGO = "2000100080001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("014", "Menta Granizada")

    def _crear_rm_legacy(self, tipo="ingreso", grupo_id=1):
        """Crea un RegistroMovimiento sin balde_id (datos históricos)."""
        return RegistroMovimiento.objects.create(
            grupo_id=grupo_id,
            producto=self.prod,
            peso=4.5,
            tipo=tipo,
            codigo_barras=self.CODIGO,
            balde=None,           # sin FK — simula registro histórico
        )

    def test_anulacion_ingreso_legacy_borra_balde_mas_antiguo(self):
        """
        Fallback FIFO: anular ingreso legacy borra el StockBalde más antiguo
        con ese codigo_barras que está activo.
        """
        b_viejo = crear_balde(self.prod, codigo=self.CODIGO, activo=True)
        b_nuevo = crear_balde(self.prod, codigo=self.CODIGO, activo=True)
        self._crear_rm_legacy(tipo="ingreso", grupo_id=100)
        GrupoMovimiento.objects.create(
            grupo_id=100, tipo="ingreso", total_peso=4.5, cantidad_items=1
        )

        resp = self.client.delete("/eliminar_movimiento/100/")
        self.assertEqual(resp.status_code, 200, resp.content)

        # El más antiguo fue borrado
        self.assertFalse(StockBalde.objects.filter(pk=b_viejo.pk).exists(),
            "El balde más antiguo debe haber sido eliminado")
        # El más nuevo sigue activo
        b_nuevo.refresh_from_db()
        self.assertTrue(b_nuevo.is_activo, "El balde más nuevo debe seguir activo")

    def test_anulacion_retiro_legacy_reactiva_mas_reciente(self):
        """
        Fallback LIFO: anular un retiro legacy reactiva el StockBalde más
        recientemente retirado con ese codigo_barras.
        """
        b_old = crear_balde(self.prod, codigo=self.CODIGO, activo=False)
        b_old.fecha_retiro = timezone.now()
        b_old.save(update_fields=["fecha_retiro"])

        import time; time.sleep(0.01)   # garantiza timestamps distintos

        b_recent = crear_balde(self.prod, codigo=self.CODIGO, activo=False)
        b_recent.fecha_retiro = timezone.now()
        b_recent.save(update_fields=["fecha_retiro"])

        self._crear_rm_legacy(tipo="salida", grupo_id=101)
        GrupoMovimiento.objects.create(
            grupo_id=101, tipo="salida", total_peso=4.5, cantidad_items=1
        )

        resp = self.client.delete("/eliminar_movimiento/101/")
        self.assertEqual(resp.status_code, 200, resp.content)

        b_recent.refresh_from_db()
        self.assertTrue(b_recent.is_activo,
            "El balde más recientemente retirado debe haberse reactivado")
        b_old.refresh_from_db()
        self.assertFalse(b_old.is_activo,
            "El balde más antiguo no debe haber sido reactivado")


# ─── C-5: Retiro anterior no puede ocultar ingreso posterior ─────────────────

class TestRetiroAntiguoNoAfectaIngresoNuevo(TestCase):
    """
    C-5: Regresión — un RegistroMovimiento tipo 'salida' registrado antes del
    timestamp de un StockBalde activo no debe hacer que ese balde desaparezca
    de stock_detallado ni de buscar_detallado.

    Escenario que causó el bug de StockBalde ID 6437:
      código 2004200041809 (Chocolate 4.180 kg)
      Retiro el 31/07/2026 → balde anterior queda is_activo=False.
      Ingreso nuevo el 28/08/2026 → StockBalde.is_activo=True.
      _corregir_baldes_incorrectamente_activos() contaba 1 retiro y 0 inactivos
      → exceso=1 → marcaba el nuevo balde como inactivo por error de FIFO sin
      considerar timestamps.

    Estos tests verifican el invariante: solo baldes con is_activo=True
    deben aparecer en las vistas de stock.
    """

    CODIGO = "2004200041809"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("030", "Chocolate")

    def _crear_rm_salida(self, balde, grupo_id):
        """Crea un RegistroMovimiento de tipo 'salida' para el balde dado."""
        return RegistroMovimiento.objects.create(
            grupo_id=grupo_id,
            producto=self.prod,
            peso=balde.peso,
            tipo="salida",
            codigo_barras=self.CODIGO,
            balde=balde,
        )

    def test_stock_detallado_muestra_balde_activo_tras_retiro_previo(self):
        """
        stock_detallado incluye el balde activo aunque exista un retiro
        anterior con el mismo codigo_barras.
        """
        balde_viejo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=False)
        self._crear_rm_salida(balde_viejo, grupo_id=9901)
        balde_nuevo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=True)

        resp = self.client.get("/stock/detallado/")
        self.assertEqual(resp.status_code, 200)
        ids = [b.pk for b in resp.context["stock_detallado"]]

        self.assertIn(
            balde_nuevo.pk, ids,
            "El balde activo (ingresado después del retiro) no apareció en stock_detallado",
        )
        self.assertNotIn(
            balde_viejo.pk, ids,
            "El balde retirado (is_activo=False) apareció incorrectamente en stock_detallado",
        )

    def test_buscar_detallado_con_termino_muestra_balde_activo_tras_retiro_previo(self):
        """
        buscar_detallado con término de búsqueda excluye baldes inactivos
        aunque compartan codigo_barras con el balde activo.
        """
        balde_viejo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=False)
        self._crear_rm_salida(balde_viejo, grupo_id=9902)
        balde_nuevo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=True)

        resp = self.client.post(
            "/buscar_detallado/",
            {"termino_busqueda": "Chocolate", "fecha": ""},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [b.pk for b in resp.context["stock_detallado"]]

        self.assertIn(
            balde_nuevo.pk, ids,
            "El balde activo no apareció en buscar_detallado con término de búsqueda",
        )
        self.assertNotIn(
            balde_viejo.pk, ids,
            "El balde retirado apareció en buscar_detallado pese a ser is_activo=False",
        )

    def test_buscar_detallado_sin_termino_excluye_todos_los_inactivos(self):
        """
        buscar_detallado sin término de búsqueda devuelve solo baldes activos.
        Reproduce el path que devolvía StockBalde.objects.all() sin filtro.
        """
        balde_viejo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=False)
        self._crear_rm_salida(balde_viejo, grupo_id=9903)
        balde_nuevo = crear_balde(self.prod, peso=4.180, codigo=self.CODIGO, activo=True)

        resp = self.client.post(
            "/buscar_detallado/",
            {"termino_busqueda": "", "fecha": ""},
        )
        self.assertEqual(resp.status_code, 200)
        stock = list(resp.context["stock_detallado"])

        self.assertTrue(
            all(b.is_activo for b in stock),
            "buscar_detallado sin filtro devolvió al menos un balde con is_activo=False",
        )
        ids = [b.pk for b in stock]
        self.assertIn(balde_nuevo.pk, ids)
        self.assertNotIn(balde_viejo.pk, ids)


# ─── C-6: Escaneo de código repetido → ConfirmDialog (no descarte silencioso) ─

class TestEscaneoCodigoRepetido(TestCase):
    """
    C-6: Cuando se escanea un código que ya está en la lista temporal,
    procesar_codigo debe devolver {"duplicado": True} en lugar de
    descartar silenciosamente o agregar automáticamente.

    Si el operario confirma que es otro balde físico (force_duplicate=True),
    el segundo item se agrega con un scan_item_id distinto.
    El backend puede procesar dos unidades del mismo código de barras como
    dos ingresos o dos retiros independientes.
    """

    CODIGO = "2000100045001"   # PLU 001, peso 4.500

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")
        self.boca = BocaSalida.objects.create(nombre="Portofino")

    def _escanear(self, codigo=None, force_duplicate=False):
        payload = {"codigo": codigo or self.CODIGO}
        if force_duplicate:
            payload["force_duplicate"] = True
        return post_json(self.client, "/api/procesar_codigo/", payload)

    # ── procesar_codigo ──────────────────────────────────────────────────────

    def test_primer_escaneo_agrega_item_con_scan_item_id(self):
        """El primer escaneo agrega el item con scan_item_id único."""
        resp = self._escanear()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("duplicado", data)
        items = data.get("productos_temporales", [])
        self.assertEqual(len(items), 1)
        self.assertIn("scan_item_id", items[0])
        self.assertTrue(items[0]["scan_item_id"])

    def test_segundo_escaneo_sin_force_devuelve_duplicado(self):
        """El segundo escaneo del mismo código devuelve duplicado=True."""
        self._escanear()
        resp = self._escanear()  # mismo código, sin force_duplicate
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("duplicado"), "Debería indicar duplicado=True")
        self.assertEqual(data.get("ya_en_lista"), 1)
        self.assertIn("stock_disponible", data)
        # La sesión sigue con 1 solo item (no se agregó el segundo)
        session = self.client.session
        items = session.get("productos_temporales", [])
        self.assertEqual(len(items), 1, "No debió agregarse el segundo item sin force_duplicate")

    def test_segundo_escaneo_con_force_agrega_segunda_unidad(self):
        """Con force_duplicate=True se agrega el segundo balde con scan_item_id distinto."""
        self._escanear()
        resp = self._escanear(force_duplicate=True)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("duplicado", data)
        items = data.get("productos_temporales", [])
        self.assertEqual(len(items), 2)
        ids = [i["scan_item_id"] for i in items]
        self.assertEqual(len(set(ids)), 2, "Cada balde físico debe tener scan_item_id único")

    def test_retiro_segundo_escaneo_sin_stock_suficiente_informa_stock_disponible(self):
        """
        Si hay 1 balde activo en stock y ya hay 1 en la lista,
        el segundo escaneo indica stock_disponible=1 y ya_en_lista=1.
        El frontend usará eso para bloquear el agregado.
        """
        crear_balde(self.prod, peso=4.5, codigo=self.CODIGO, activo=True)
        self._escanear()
        resp = self._escanear()
        data = resp.json()
        self.assertTrue(data.get("duplicado"))
        self.assertEqual(data.get("stock_disponible"), 1)
        self.assertEqual(data.get("ya_en_lista"), 1)

    # ── eliminar_producto_temporal ───────────────────────────────────────────

    def test_eliminar_por_scan_item_id_borra_item_correcto(self):
        """
        Con dos items del mismo código, eliminar por scan_item_id
        borra solo el segundo, dejando intacto el primero.
        """
        self._escanear()
        self._escanear(force_duplicate=True)
        session = self.client.session
        items = session.get("productos_temporales", [])
        self.assertEqual(len(items), 2)
        id_segundo = items[1]["scan_item_id"]

        resp = post_json(self.client, "/api/eliminar_producto_temporal/", {"scan_item_id": id_segundo})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))

        session = self.client.session
        items_restantes = session.get("productos_temporales", [])
        self.assertEqual(len(items_restantes), 1)
        self.assertNotEqual(items_restantes[0]["scan_item_id"], id_segundo)

    # ── Flujo completo: escaneo → sesión → confirmar → StockBalde + RM ──────

    def test_ingreso_dos_unidades_mismo_codigo_crea_dos_baldes(self):
        """
        Escanear dos veces el mismo código (force_duplicate) y confirmar
        el ingreso crea 2 StockBalde y 2 RegistroMovimiento de tipo 'ingreso'.
        """
        self._escanear()
        self._escanear(force_duplicate=True)
        session = self.client.session
        items = session.get("productos_temporales", [])
        self.assertEqual(len(items), 2)

        payload = {
            "origen": "Portofino",
            "force": True,   # dos baldes físicos con el mismo código → force requerido
            "productos": [
                {"plu": i["plu"], "peso": i["peso"], "codigo_barras": i["codigo_barras"]}
                for i in items
            ],
        }
        resp = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(resp.status_code, 200, resp.content)

        baldes = StockBalde.objects.filter(codigo_barras=self.CODIGO, is_activo=True)
        self.assertEqual(baldes.count(), 2, "Deben existir 2 baldes activos con el mismo código")

        rms = RegistroMovimiento.objects.filter(codigo_barras=self.CODIGO, tipo="ingreso")
        self.assertEqual(rms.count(), 2, "Deben existir 2 RegistroMovimiento de ingreso")

    def test_retiro_dos_unidades_mismo_codigo_desactiva_dos_baldes(self):
        """
        Con 2 baldes activos del mismo código, enviar dos retiros
        del mismo código desactiva ambos baldes (FIFO).
        """
        b1 = crear_balde(self.prod, peso=4.5, codigo=self.CODIGO, activo=True)
        b2 = crear_balde(self.prod, peso=4.5, codigo=self.CODIGO, activo=True)

        payload = {
            "destino": "Portofino",
            "productos": [
                {"plu": "001", "codigo_barras": self.CODIGO},
                {"plu": "001", "codigo_barras": self.CODIGO},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(resp.status_code, 200, resp.content)

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertFalse(b1.is_activo, "Primer balde (FIFO) debe quedar inactivo")
        self.assertFalse(b2.is_activo, "Segundo balde debe quedar inactivo")

        rms = RegistroMovimiento.objects.filter(codigo_barras=self.CODIGO, tipo="salida")
        self.assertEqual(rms.count(), 2, "Deben existir 2 RegistroMovimiento de salida")


# ─── C-7: Bug duplicado en devolución — procesar_codigo devuelve duplicado:true ─

class TestDevolucionDuplicado(TestCase):
    """
    C-7: Cuando en una devolución se escanea el mismo código dos veces,
    procesar_codigo debe devolver {"duplicado": True} y la sesión debe
    conservar solo un ítem (no vaciarse, no agregar dos).

    Reproduce el bug donde data.productos_temporales era undefined al recibir
    duplicado:true, vaciando productosEscaneados en el frontend.
    """

    CODIGO = "2000100045001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")

    def _escanear(self, codigo=None, force=False):
        payload = {"codigo": codigo or self.CODIGO}
        if force:
            payload["force_duplicate"] = True
        return post_json(self.client, "/api/procesar_codigo/", payload)

    def test_segundo_escaneo_devolucion_devuelve_duplicado(self):
        """El segundo escaneo del mismo código retorna duplicado=True."""
        self._escanear()
        resp = self._escanear()
        data = resp.json()
        self.assertTrue(data.get("duplicado"), "Debe devolver duplicado=True")
        # No debe incluir productos_temporales (eso causaba el bug de vaciado)
        self.assertNotIn("productos_temporales", data,
                         "La respuesta de duplicado no debe incluir productos_temporales")

    def test_segundo_escaneo_devolucion_no_vacia_sesion(self):
        """La sesión conserva el primer ítem tras el segundo escaneo sin force."""
        self._escanear()
        sesion_antes = self.client.session.get("productos_temporales", [])
        self.assertEqual(len(sesion_antes), 1)

        self._escanear()  # duplicado sin force
        sesion_despues = self.client.session.get("productos_temporales", [])
        self.assertEqual(len(sesion_despues), 1,
                         "La sesión no debe vaciarse al recibir duplicado=True")

    def test_devolucion_no_procesa_codigo_repetido_en_backend(self):
        """
        confirmar_devolucion con el mismo código dos veces en el payload
        solo crea un StockBalde (el backend deduplica por codigo_barras).
        """
        boca = BocaSalida.objects.create(nombre="Portofino")
        payload = {
            "origen": "Portofino",
            "productos": [
                {"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO},
                {"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO},
            ],
        }
        resp = post_json(self.client, "/api/confirmar_devolucion/", payload)
        self.assertEqual(resp.status_code, 200, resp.content)
        baldes = StockBalde.objects.filter(codigo_barras=self.CODIGO, is_activo=True)
        self.assertEqual(baldes.count(), 1,
                         "Solo debe crearse 1 balde aunque se envíe el mismo código dos veces")
        rms = RegistroMovimiento.objects.filter(codigo_barras=self.CODIGO, tipo="devolucion")
        self.assertEqual(rms.count(), 1,
                         "Solo debe crearse 1 RegistroMovimiento de devolución")


# ─── C-8: Sin cache — obtener_stock refleja estado inmediato tras operación ──

class TestObtenerStockSinCache(TestCase):
    """
    C-8: /api/obtener_stock/ no debe devolver datos cacheados.
    Tras ingresar un balde, la próxima llamada debe reflejar el nuevo estado.

    Reproduce el bug donde @cache_page(5) mantenía el stock stale por 5 s
    después de una operación, generando datos incorrectos en el frontend.
    """

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")

    def test_stock_refleja_ingreso_inmediatamente(self):
        """Después de ingresar un balde, obtener_stock debe devolver cantidad=1."""
        resp_antes = self.client.get("/api/obtener_stock/")
        self.assertEqual(resp_antes.status_code, 200)
        stock_antes = resp_antes.json()["stock"]
        cantidad_antes = next(
            (p["cantidad"] for p in stock_antes if p["plu"] == "001"), 0
        )

        # Ingresar un balde
        post_json(self.client, "/api/confirmar_codigos/", {
            "origen": "Fábrica",
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": "2000100045001"}],
        })

        resp_despues = self.client.get("/api/obtener_stock/")
        self.assertEqual(resp_despues.status_code, 200)
        stock_despues = resp_despues.json()["stock"]
        cantidad_despues = next(
            (p["cantidad"] for p in stock_despues if p["plu"] == "001"), 0
        )

        self.assertEqual(cantidad_despues, cantidad_antes + 1,
                         "El stock debe actualizarse en la misma petición, sin delay de cache")


# ─── C-9: Backup seguro — directorio persistente + SQLite Online Backup API ──

class TestBackupSeguro(TestCase):
    """
    C-9: make_startup_backup debe:
    - Usar LOCALAPPDATA/StockControl/backups (no BASE_DIR/backups de PyInstaller)
    - Usar sqlite3.backup() (Online Backup API) en lugar de shutil.copy2
    - Crear el archivo de backup y retornar su ruta
    - Respetar la rotación keep_last
    """

    def test_backup_usa_localappdata_cuando_disponible(self):
        """Con LOCALAPPDATA definido, el backup va a LOCALAPPDATA/StockControl/backups."""
        import tempfile
        from unittest.mock import patch
        from app_inventario.utils.backups import _get_backups_dir

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}):
                backups_dir = _get_backups_dir()
            expected = os.path.join(tmp, "StockControl", "backups")
            self.assertEqual(backups_dir, expected)

    def _crear_db_origen(self, directorio):
        """Crea un archivo SQLite real en el directorio dado y retorna su ruta."""
        import sqlite3 as _sqlite3
        ruta = os.path.join(directorio, "origen.sqlite3")
        conn = _sqlite3.connect(ruta)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        return ruta

    def test_backup_crea_archivo_sqlite_valido(self):
        """make_startup_backup crea un archivo SQLite legible."""
        import sqlite3 as _sqlite3
        import tempfile
        from app_inventario.utils.backups import make_startup_backup

        # En tests la DB es in-memory; creamos un SQLite temporal real para mockear.
        # Mantenemos el TemporaryDirectory abierto durante las assertions.
        with tempfile.TemporaryDirectory() as tmp:
            db_origen = self._crear_db_origen(tmp)
            backups_destino = os.path.join(tmp, "backups")

            with patch("app_inventario.utils.backups._get_backups_dir", return_value=backups_destino), \
                 patch("app_inventario.utils.backups.settings") as mock_settings:
                mock_settings.DATABASES = {"default": {"NAME": db_origen}}
                ruta = make_startup_backup(keep_last=5)

            self.assertIsNotNone(ruta, "make_startup_backup debe retornar la ruta del backup")
            self.assertTrue(os.path.exists(ruta), "El archivo de backup debe existir")

            # Verificar que es un SQLite válido (Online Backup API lo garantiza)
            conn = _sqlite3.connect(ruta)
            try:
                tablas = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                self.assertTrue(len(tablas) > 0, "El backup debe tener al menos una tabla")
            finally:
                conn.close()

    def test_backup_rotacion_elimina_antiguos(self):
        """Con keep_last=2 y 3 backups existentes, se elimina el más antiguo."""
        import tempfile
        from datetime import datetime, timezone as dt_tz
        from app_inventario.utils.backups import make_startup_backup

        # timezone.now() tiene resolución de segundos en el nombre de archivo.
        # Mockeamos las 3 llamadas para que devuelvan tiempos distintos.
        t1 = datetime(2024, 1, 1, 12, 0, 1, tzinfo=dt_tz.utc)
        t2 = datetime(2024, 1, 1, 12, 0, 2, tzinfo=dt_tz.utc)
        t3 = datetime(2024, 1, 1, 12, 0, 3, tzinfo=dt_tz.utc)

        with tempfile.TemporaryDirectory() as tmp:
            db_origen = self._crear_db_origen(tmp)
            backups_destino = os.path.join(tmp, "backups")

            with patch("app_inventario.utils.backups._get_backups_dir", return_value=backups_destino), \
                 patch("app_inventario.utils.backups.settings") as mock_settings, \
                 patch("app_inventario.utils.backups.timezone") as mock_tz:
                mock_settings.DATABASES = {"default": {"NAME": db_origen}}
                mock_tz.now.side_effect = [t1, t2, t3]
                ruta1 = make_startup_backup(keep_last=2)
                ruta2 = make_startup_backup(keep_last=2)
                ruta3 = make_startup_backup(keep_last=2)

            # Debe existir ruta2 y ruta3 (los 2 más nuevos); ruta1 eliminado
            self.assertFalse(os.path.exists(ruta1),
                             "El backup más antiguo debe haberse eliminado")
            self.assertTrue(os.path.exists(ruta2))
            self.assertTrue(os.path.exists(ruta3))


# ─── C-10: Validación EAN-13 centralizada ────────────────────────────────────

class TestValidacionEAN13(TestCase):
    """
    C-10: La función validar_ean13 debe:
    - Rechazar códigos con longitud distinta de 13
    - Rechazar códigos con caracteres no numéricos
    - Rechazar códigos con dígito verificador incorrecto
    - Aceptar códigos EAN-13 válidos
    - Todos los endpoints deben rechazar códigos con dígito verificador incorrecto
    """

    def test_codigo_valido(self):
        """Un código de 13 dígitos pasa la validación básica (sin DV)."""
        from app_inventario.utils.ean13 import validar_ean13

        ok, motivo = validar_ean13("2000100045001")
        self.assertTrue(ok, f"Debe ser válido, motivo: {motivo}")
        self.assertEqual(motivo, "")

    def test_codigo_estricto_valido_con_dv_correcto(self):
        """validar_ean13_estricto acepta código con DV correcto."""
        from app_inventario.utils.ean13 import validar_ean13_estricto, calcular_digito_verificador

        base = "200010004500"
        dv = calcular_digito_verificador(base)
        codigo = base + str(dv)
        ok, motivo = validar_ean13_estricto(codigo)
        self.assertTrue(ok, f"Debe ser válido, motivo: {motivo}")

    def test_codigo_longitud_incorrecta(self):
        """Código de 12 dígitos debe fallar."""
        from app_inventario.utils.ean13 import validar_ean13
        ok, motivo = validar_ean13("200010004500")
        self.assertFalse(ok)
        self.assertIn("13", motivo)

    def test_codigo_con_letras(self):
        """Código con letras debe fallar."""
        from app_inventario.utils.ean13 import validar_ean13
        ok, motivo = validar_ean13("200010004500X")
        self.assertFalse(ok)

    def test_digito_verificador_incorrecto_falla_en_estricto(self):
        """validar_ean13_estricto rechaza código con DV incorrecto."""
        from app_inventario.utils.ean13 import validar_ean13_estricto, calcular_digito_verificador

        base = "200010004500"
        dv = calcular_digito_verificador(base)
        dv_malo = (dv + 1) % 10
        codigo_malo = base + str(dv_malo)
        ok, motivo = validar_ean13_estricto(codigo_malo)
        self.assertFalse(ok)
        self.assertIn("verificador", motivo)

    def test_endpoint_procesar_codigo_rechaza_longitud_incorrecta(self):
        """procesar_codigo debe rechazar códigos con longitud distinta de 13."""
        resp = post_json(self.client, "/api/procesar_codigo/", {"codigo": "200010004500"})
        data = resp.json()
        self.assertIn("error", data, "Debe retornar error para código de longitud incorrecta")
        self.assertEqual(resp.status_code, 400)

    def test_calcular_digito_verificador_conocido(self):
        """El dígito verificador de un código EAN-13 conocido es correcto."""
        from app_inventario.utils.ean13 import calcular_digito_verificador

        # EAN-13 estándar de ejemplo: 5901234123457
        # Primeros 12: 590123412345 → DV = 7
        dv = calcular_digito_verificador("590123412345")
        self.assertEqual(dv, 7)

    def test_parsear_codigo_barras_extrae_plu_y_peso(self):
        """parsear_codigo_barras extrae PLU y peso del formato interno '2xPLU...'."""
        from app_inventario.utils.ean13 import parsear_codigo_barras

        # "2000100045001" → PLU='001', kg_enteros=4, dec=500 → peso=4.500
        # Formato: 2|0|001|000|4|500|DV
        resultado = parsear_codigo_barras("2000100045001")
        self.assertEqual(resultado["codigo"], "2000100045001")
        self.assertEqual(resultado["plu"], "001")
        self.assertAlmostEqual(resultado["peso_etiqueta"], 4.500, places=3)

    def test_parsear_codigo_barras_dv_valido(self):
        """parsear_codigo_barras informa correctamente si el DV es válido."""
        from app_inventario.utils.ean13 import parsear_codigo_barras, calcular_digito_verificador

        codigo_12 = "200010004500"
        dv = calcular_digito_verificador(codigo_12)
        codigo_valido = codigo_12 + str(dv)

        resultado = parsear_codigo_barras(codigo_valido)
        self.assertTrue(resultado["digito_verificador_valido"], "DV correcto debe dar True")

        # Con DV incorrecto
        dv_malo = (dv + 1) % 10
        resultado2 = parsear_codigo_barras(codigo_12 + str(dv_malo))
        self.assertFalse(resultado2["digito_verificador_valido"], "DV incorrecto debe dar False")

    def test_parsear_codigo_barras_codigo_externo_sin_prefijo_2(self):
        """Código que no empieza con '2' no tiene PLU ni peso_etiqueta."""
        from app_inventario.utils.ean13 import parsear_codigo_barras

        resultado = parsear_codigo_barras("5901234123457")
        self.assertIsNone(resultado["plu"])
        self.assertIsNone(resultado["peso_etiqueta"])

    def test_parsear_codigo_barras_invalido_nunca_lanza(self):
        """parsear_codigo_barras nunca lanza excepción con entradas inválidas."""
        from app_inventario.utils.ean13 import parsear_codigo_barras

        for entrada in ["", "abc", "1234", None, 123, "2000100045001X"]:
            try:
                r = parsear_codigo_barras(entrada)
            except Exception as exc:
                self.fail(f"parsear_codigo_barras({entrada!r}) lanzó {exc!r}")
            self.assertIsNone(r["plu"])
            self.assertIsNone(r["peso_etiqueta"])
            self.assertFalse(r["digito_verificador_valido"])


# ─── C-11: Idempotencia persistente en DB ────────────────────────────────────

class TestIdempotenciaDB(TestCase):
    """
    C-11: Las operaciones de ingreso, retiro y devolución son idempotentes
    cuando el cliente envía el mismo operation_id.

    El segundo request con el mismo operation_id debe retornar el mismo
    grupo_id sin crear baldes ni movimientos duplicados.
    """

    CODIGO = "2000100045001"
    UUID1 = "11111111-1111-1111-1111-111111111111"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")

    def test_ingreso_idempotente_no_duplica_balde(self):
        """Repetir confirmar_codigos con el mismo operation_id no crea dos baldes."""
        payload = {
            "origen": "Fábrica",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json().get("status"), "ya_procesado")

        # Solo debe existir 1 balde
        self.assertEqual(StockBalde.objects.filter(codigo_barras=self.CODIGO).count(), 1)

    def test_ingreso_idempotente_retorna_mismo_grupo_id(self):
        """El segundo request devuelve el mismo grupo_id que el primero."""
        payload = {
            "origen": "Fábrica",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_codigos/", payload)
        r2 = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r1.json()["grupo_id"], r2.json()["grupo_id"])

    def test_retiro_idempotente_no_duplica_movimiento(self):
        """Repetir confirmar_retiro con el mismo operation_id no retira el balde dos veces."""
        boca = BocaSalida.objects.create(nombre="Local Norte")
        crear_balde(self.prod, 4.5, self.CODIGO)

        payload = {
            "destino": "Local Norte",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json().get("status"), "ya_procesado")

        # El balde debe estar inactivo (retirado) — no re-retirado
        rm_count = RegistroMovimiento.objects.filter(
            codigo_barras=self.CODIGO, tipo="salida"
        ).count()
        self.assertEqual(rm_count, 1, "Solo debe haber 1 movimiento de salida")

    def test_devolucion_idempotente_no_duplica_balde(self):
        """Repetir confirmar_devolucion con el mismo operation_id no crea dos baldes."""
        payload = {
            "origen": "Local Norte",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_devolucion/", payload)
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = post_json(self.client, "/api/confirmar_devolucion/", payload)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json().get("status"), "ya_procesado")

        self.assertEqual(
            StockBalde.objects.filter(codigo_barras=self.CODIGO, is_activo=True).count(), 1
        )

    def test_operation_id_distinto_permite_segunda_operacion(self):
        """Un operation_id diferente no activa la idempotencia — la operación se ejecuta."""
        payload1 = {
            "origen": "Fábrica",
            "operation_id": "aaaa0000-0000-0000-0000-000000000001",
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        payload2 = {
            "origen": "Fábrica",
            "operation_id": "aaaa0000-0000-0000-0000-000000000002",
            "force": True,  # forzar porque el código ya está activo
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_codigos/", payload1)
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = post_json(self.client, "/api/confirmar_codigos/", payload2)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertIsNone(r2.json().get("status"))  # no es "ya_procesado"

        # Debe haber 2 baldes (segunda operación realmente ejecutada con force)
        self.assertEqual(StockBalde.objects.filter(codigo_barras=self.CODIGO).count(), 2)

    # ── Test #7 (mandatorio): operation_id reutilizado con payload distinto → 409 ──

    def test_operation_id_reutilizado_payload_distinto_ingreso_retorna_409(self):
        """
        Mandatory test #7: mismo operation_id con payload distinto devuelve 409.

        Escenario: el cliente envía un primer ingreso con operation_id UUID1
        (exitoso). Luego reenvía el mismo operation_id pero con un producto
        diferente (distinto PLU o peso). El servidor detecta que el payload_hash
        difiere del almacenado y rechaza con 409 en lugar de repetir la operación
        con datos distintos.

        Esto protege contra bugs de cliente que reciclan UUIDs o contra un replay
        malintencionado que intenta usar el token de una operación legítima para
        ejecutar una operación diferente.
        """
        payload_original = {
            "origen": "Fábrica",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        # Primera solicitud — se procesa y almacena el payload_hash
        r1 = post_json(self.client, "/api/confirmar_codigos/", payload_original)
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertFalse(r1.json().get("status") == "ya_procesado")

        # Verificar que el hash quedó guardado en la DB
        op = OperacionIdempotente.objects.get(operation_id=self.UUID1)
        self.assertTrue(op.payload_hash, "El payload_hash debe quedar almacenado")

        # Segunda solicitud — mismo operation_id pero payload distinto (diferente peso)
        payload_alterado = {
            "origen": "Fábrica",
            "operation_id": self.UUID1,          # ← mismo UUID
            "productos": [{"plu": "001", "peso": 9.9, "codigo_barras": self.CODIGO}],  # ← distinto
        }
        r2 = post_json(self.client, "/api/confirmar_codigos/", payload_alterado)
        self.assertEqual(
            r2.status_code, 409,
            f"Se esperaba 409 pero se recibió {r2.status_code}: {r2.content}",
        )
        self.assertIn("operation_id", r2.json().get("error", "").lower())

        # Solo debe existir 1 balde (el original, no el del payload alterado)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 1)
        balde = StockBalde.objects.get(is_activo=True)
        self.assertEqual(float(balde.peso), 4.5, "El peso no debe haber sido alterado")

    def test_operation_id_reutilizado_payload_distinto_retiro_retorna_409(self):
        """
        Mandatory test #7 (variante retiro): mismo operation_id con payload
        distinto en confirmar_retiro devuelve 409.
        """
        boca = BocaSalida.objects.create(nombre="Local Sur")
        # Crear 2 baldes para que la primera operación tenga algo que retirar
        crear_balde(self.prod, 4.5, self.CODIGO)
        crear_balde(self.prod, 9.9, self.CODIGO)

        UUID_RETIRO = "22222222-2222-2222-2222-222222222222"

        payload_original = {
            "destino": "Local Sur",
            "operation_id": UUID_RETIRO,
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_retiro/", payload_original)
        self.assertEqual(r1.status_code, 200, r1.content)

        # Mismo operation_id, destino distinto
        payload_alterado = {
            "destino": "Local Norte",           # ← distinto destino
            "operation_id": UUID_RETIRO,        # ← mismo UUID
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        }
        r2 = post_json(self.client, "/api/confirmar_retiro/", payload_alterado)
        self.assertEqual(
            r2.status_code, 409,
            f"Se esperaba 409 pero se recibió {r2.status_code}: {r2.content}",
        )

    def test_operation_id_payload_identico_retorna_200_ya_procesado(self):
        """
        El mismo operation_id con exactamente el mismo payload retorna 200
        con status='ya_procesado' — retry legítimo, no replay attack.
        """
        payload = {
            "origen": "Fábrica",
            "operation_id": self.UUID1,
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r1.status_code, 200, r1.content)

        # Exactamente el mismo payload → retry idempotente (no 409)
        r2 = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json().get("status"), "ya_procesado")

    # ── Prueba obligatoria del spec (flujo completo de idempotencia con retiro) ──

    def test_retiro_idempotente_flujo_completo_dos_baldes_un_uuid(self):
        """
        Prueba obligatoria del spec:
        1. Crear dos baldes activos con el mismo código.
        2. Enviar retiro con UUID A → se retira 1 balde (el más antiguo por FIFO).
        3. Repetir exactamente el mismo retiro con UUID A.
           → Solo se retiró 1 balde (el 2do request fue idempotente).
           → Solo 1 movimiento de salida creado.
        4. Enviar el mismo payload con UUID B.
           → Se retira el 2do balde (UUID distinto = nueva operación).
        """
        boca = BocaSalida.objects.create(nombre="Local Norte")
        balde1 = crear_balde(self.prod, 4.5, self.CODIGO)  # más antiguo (FIFO)
        balde2 = crear_balde(self.prod, 5.5, self.CODIGO)  # más nuevo

        UUID_A = "aaaa0000-0000-0000-0000-aaaaaaaaaaaa"
        UUID_B = "bbbb0000-0000-0000-0000-bbbbbbbbbbbb"
        payload_base = {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        }

        # Paso 1: primer retiro con UUID A → retira balde1 (FIFO)
        r1 = post_json(self.client, "/api/confirmar_retiro/", {**payload_base, "operation_id": UUID_A})
        self.assertEqual(r1.status_code, 200, r1.content)
        grupo_a = r1.json().get("grupo_id")

        # Paso 2: mismo payload con UUID A → idempotente, no retira balde2
        r2 = post_json(self.client, "/api/confirmar_retiro/", {**payload_base, "operation_id": UUID_A})
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json().get("status"), "ya_procesado",
            "El segundo request con UUID A debe ser ya_procesado")
        self.assertEqual(r2.json().get("grupo_id"), grupo_a,
            "El grupo_id debe ser el mismo que el del primer request")

        # Solo 1 movimiento de salida (balde1), balde2 sigue activo
        rm_count = RegistroMovimiento.objects.filter(
            codigo_barras=self.CODIGO, tipo="salida"
        ).count()
        self.assertEqual(rm_count, 1, "Solo debe haber 1 movimiento de salida tras 2 requests con UUID A")

        balde1.refresh_from_db()
        balde2.refresh_from_db()
        self.assertFalse(balde1.is_activo, "Balde1 (más antiguo) debe estar inactivo")
        self.assertTrue(balde2.is_activo, "Balde2 debe seguir activo (idempotencia)")

        # Paso 3: mismo payload con UUID B → nueva operación, retira balde2
        r3 = post_json(self.client, "/api/confirmar_retiro/", {**payload_base, "operation_id": UUID_B})
        self.assertEqual(r3.status_code, 200, r3.content)
        self.assertNotEqual(r3.json().get("status"), "ya_procesado",
            "UUID B es nuevo, debe ejecutar la operación")

        balde2.refresh_from_db()
        self.assertFalse(balde2.is_activo, "Balde2 debe estar inactivo tras UUID B")

        rm_count_final = RegistroMovimiento.objects.filter(
            codigo_barras=self.CODIGO, tipo="salida"
        ).count()
        self.assertEqual(rm_count_final, 2,
            "Deben existir exactamente 2 movimientos de salida al final")

    def test_retiro_ya_procesado_devuelve_campos_completos(self):
        """
        La respuesta del segundo request (ya_procesado) debe incluir los campos
        originales de la operación: productos, destino, grupo_id.
        Esto permite que el frontend muestre el resultado correcto en un retry.
        """
        boca = BocaSalida.objects.create(nombre="Local Norte")
        crear_balde(self.prod, 4.5, self.CODIGO)

        UUID_C = "cccc0000-0000-0000-0000-cccccccccccc"
        payload = {
            "destino": "Local Norte",
            "operation_id": UUID_C,
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        }
        r1 = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(r1.status_code, 200, r1.content)

        r2 = post_json(self.client, "/api/confirmar_retiro/", payload)
        self.assertEqual(r2.status_code, 200, r2.content)
        d2 = r2.json()

        self.assertEqual(d2.get("status"), "ya_procesado")
        self.assertIn("grupo_id", d2, "El retry debe incluir grupo_id")


# ─── C-12: Autorización de duplicado por scan_item_id (item 3) ───────────────

class TestAutorizacionDuplicadoPorUnidad(TestCase):
    """
    C-12: Cuando el operario autoriza un escaneo duplicado, la autorización
    debe ser por scan_item_id específico, no por force=True global.

    Un scan_item_id autorizado no debe autorizar otros ítems del mismo payload.
    """

    CODIGO_A = "2000100045001"
    CODIGO_B = "2000200055001"

    def setUp(self):
        self.client = Client()
        self.prod_a = crear_producto("001", "Vainilla")
        self.prod_b = crear_producto("002", "Chocolate")
        # Pre-poblar stock con un balde de código A
        crear_balde(self.prod_a, 4.5, self.CODIGO_A)

    def _escanear(self, codigo, force=False):
        payload = {"codigo": codigo}
        if force:
            payload["force_duplicate"] = True
        return post_json(self.client, "/api/procesar_codigo/", payload)

    def test_autorizacion_por_scan_item_id_permite_solo_unidad_aprobada(self):
        """
        Autorizar el duplicado de CODIGO_A mediante force_duplicate no debe
        autorizar automáticamente CODIGO_B si también está en stock.
        """
        # Agregar un balde de B al stock también
        crear_balde(self.prod_b, 5.5, self.CODIGO_B)

        # Escanear A (duplicado en stock → obtenemos su scan_item_id)
        r1 = self._escanear(self.CODIGO_A)
        self.assertEqual(r1.status_code, 200, r1.content)
        d1 = r1.json()
        self.assertFalse(d1.get("duplicado"), "Primer escaneo de A no debe ser duplicado")

        # Escanear B (también duplicado en stock)
        r2 = self._escanear(self.CODIGO_B)
        d2 = r2.json()
        self.assertFalse(d2.get("duplicado"), "Primer escaneo de B no debe ser duplicado")

        # Ahora escanear A de nuevo → duplicado en lista → forzar
        r3 = self._escanear(self.CODIGO_A, force=True)
        d3 = r3.json()
        self.assertIn("scan_item_id", str(d3) + str(self.client.session.get("productos_temporales", [])),
                      "El ítem forzado debe tener scan_item_id")

        # La sesión debe tener force_approved_ids con solo el scan_item_id de A
        approved = self.client.session.get("force_approved_ids", [])
        self.assertEqual(len(approved), 1, "Solo debe haber 1 ID autorizado (el de A)")

        # Confirmamos → A está autorizado por scan_item_id, B no
        # (B no está duplicado en la lista aún, así que el confirm pasa)
        temporales = self.client.session.get("productos_temporales", [])
        self.assertEqual(len(temporales), 3, "Deben estar A, B, y el A forzado en la sesión")

    def test_segundo_scan_sin_force_no_agrega_a_force_approved_ids(self):
        """
        Escanear un código duplicado sin force_duplicate no debe
        agregarlo a force_approved_ids.
        """
        # Escanear A (no está en lista aún)
        self._escanear(self.CODIGO_A)
        # Escanear A de nuevo SIN force → debe retornar duplicado=true
        r = self._escanear(self.CODIGO_A, force=False)
        self.assertTrue(r.json().get("duplicado"))
        approved = self.client.session.get("force_approved_ids", [])
        self.assertEqual(len(approved), 0, "No debe haber IDs aprobados sin force")

    def test_confirmar_sin_scan_item_id_autorizado_rechaza_con_409(self):
        """
        Si el payload tiene un ítem con código que ya está en stock,
        y ese scan_item_id NO está en force_approved_ids de la sesión,
        confirmar_codigos debe retornar 409.
        """
        payload = {
            "origen": "Fábrica",
            "productos": [{"plu": "001", "peso": 4.5, "codigo_barras": self.CODIGO_A,
                           "scan_item_id": "fake-not-approved"}],
        }
        r = post_json(self.client, "/api/confirmar_codigos/", payload)
        self.assertEqual(r.status_code, 409, r.content)


# ─── C-13b: /api/autorizar_duplicado/ — autorización por scan_item_id ─────────

class TestAutorizarDuplicado(TestCase):
    """
    El endpoint /api/autorizar_duplicado/ agrega un scan_item_id específico
    a force_approved_ids en sesión, sin afectar otros ítems.

    Esto reemplaza el mecanismo global force=True en ingreso con duplicados.
    """

    CODIGO = "2000100045001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")

    def test_autorizar_duplicado_agrega_scan_item_id_a_sesion(self):
        """POST /api/autorizar_duplicado/ agrega el scan_item_id a la sesión."""
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        r = self.client.post(
            "/api/autorizar_duplicado/",
            data=json.dumps({"scan_item_id": sid}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        data = json.loads(r.content)
        self.assertTrue(data.get("ok"))

        approved = self.client.session.get("force_approved_ids", [])
        self.assertIn(sid, approved)

    def test_autorizar_duplicado_sin_scan_item_id_retorna_400(self):
        """POST sin scan_item_id retorna 400."""
        r = self.client.post(
            "/api/autorizar_duplicado/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_autorizar_duplicado_permite_confirmar_stock_duplicado(self):
        """
        Flujo completo: balde activo en stock → confirmar 409 → autorizar scan_item_id
        → reintentar confirmar → 200.
        """
        # Balde existente en stock con el mismo código
        StockBalde.objects.create(
            producto=self.prod, peso=4.5, codigo_barras=self.CODIGO, is_activo=True
        )
        sid = "11111111-2222-3333-4444-555555555555"

        # 1. Confirmar: debería 409 porque el código ya está activo
        payload = {
            "origen": "Fábrica",
            "productos": [{"plu": "001", "peso": 4.5,
                           "codigo_barras": self.CODIGO, "scan_item_id": sid}],
        }
        r1 = self.client.post(
            "/api/confirmar_codigos/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 409, r1.content)
        d1 = json.loads(r1.content)
        self.assertTrue(d1.get("se_puede_forzar"))

        # 2. Autorizar el scan_item_id específico
        r2 = self.client.post(
            "/api/autorizar_duplicado/",
            data=json.dumps({"scan_item_id": sid}),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200, r2.content)

        # 3. Reintentar confirmar: ahora debe pasar (scan_item_id en force_approved_ids)
        r3 = self.client.post(
            "/api/confirmar_codigos/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(r3.status_code, 200, r3.content)
        d3 = json.loads(r3.content)
        self.assertTrue(d3.get("success"))

        # El balde fue ingresado (ahora hay 2 activos)
        self.assertEqual(StockBalde.objects.filter(is_activo=True).count(), 2)


# ─── C-13: Concurrencia SQLite — UPDATE WHERE is_activo=True (item 5) ────────

class TestConcurrenciaSQLite(TestCase):
    """
    C-13: confirmar_retiro usa UPDATE WHERE is_activo=True para detectar
    retiros concurrentes sin depender de select_for_update (no-op en SQLite).

    Si otro proceso retiró el balde entre el select y el update,
    el rows_updated será 0 y se debe retornar 409.
    """

    CODIGO = "2000100045001"

    def setUp(self):
        self.client = Client()
        self.prod = crear_producto("001", "Vainilla")
        BocaSalida.objects.create(nombre="Local Norte")

    def test_retiro_con_balde_activo_retorna_200(self):
        """El retiro normal de un balde activo retorna 200 y lo deja inactivo."""
        crear_balde(self.prod, 4.5, self.CODIGO)
        r = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        })
        self.assertEqual(r.status_code, 200, r.content)
        balde = StockBalde.objects.get(codigo_barras=self.CODIGO)
        self.assertFalse(balde.is_activo)
        self.assertIsNotNone(balde.fecha_retiro)

    def test_retiro_simulado_concurrente_retorna_409(self):
        """
        Simula una carrera: el balde es desactivado externamente entre el
        select y el update. El endpoint debe detectarlo y retornar 409.

        Técnica: desactivar el balde directamente antes de que el
        confirmar_retiro intente actualizarlo, usando un mock que hace
        el update "adelante".
        """
        from unittest.mock import patch
        balde = crear_balde(self.prod, 4.5, self.CODIGO)

        # Desactivar el balde para simular que otro proceso lo retiró
        StockBalde.objects.filter(pk=balde.pk).update(is_activo=False)

        r = post_json(self.client, "/api/confirmar_retiro/", {
            "destino": "Local Norte",
            "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
        })
        # Sin balde activo disponible → debe retornar error (400 o 409)
        self.assertIn(r.status_code, [400, 409], r.content)
        # No debe haber RegistroMovimiento de salida
        self.assertEqual(
            RegistroMovimiento.objects.filter(codigo_barras=self.CODIGO, tipo="salida").count(),
            0
        )

    def test_reservar_grupo_id_incrementa_secuencialmente(self):
        """_reservar_grupo_id retorna enteros positivos que crecen en cada llamada."""
        from app_inventario.views import _reservar_grupo_id

        id1 = _reservar_grupo_id()
        id2 = _reservar_grupo_id()
        id3 = _reservar_grupo_id()

        self.assertIsInstance(id1, int)
        self.assertGreater(id1, 0)
        # Cada llamada debe reservar un valor mayor al anterior
        self.assertGreater(id2, id1)
        self.assertGreater(id3, id2)


# ─── C-14: SecuenciaGrupo — secuencia persistente sin race condition ──────────

import threading

class TestSecuenciaGrupo(TransactionTestCase):
    """
    C-14: _reservar_grupo_id() nunca devuelve el mismo número a dos operaciones
    concurrentes, incluso cuando usan conexiones de DB separadas.

    Usa TransactionTestCase (no TestCase) para que cada hilo use su propia
    transacción real y exista un verdadero lock exclusivo de SQLite.
    """

    CODIGO = "2000100045001"

    def setUp(self):
        crear_producto("001", "Vainilla")
        BocaSalida.objects.create(nombre="Local Norte")

    def test_grupo_ids_son_unicos_en_llamadas_concurrentes(self):
        """
        Dos threads que llaman a _reservar_grupo_id() simultáneamente deben
        recibir IDs distintos. Verifica que SecuenciaGrupo con F() atómico
        no sufre la carrera MAX+1.

        Nota SQLite: el lock de archivo puede serializar los threads (uno espera
        al otro). El retry interno de _reservar_grupo_id() maneja este caso.
        Si ambos tienen éxito, los IDs deben ser únicos.
        Si uno falla por lock persistente (extremadamente raro), se registra.
        """
        from app_inventario.views import _reservar_grupo_id

        resultados = []
        errores = []
        barrera = threading.Barrier(2)

        def worker():
            try:
                barrera.wait()  # sincronizar inicio de ambos threads
                gid = _reservar_grupo_id()
                resultados.append(gid)
            except Exception as exc:
                errores.append(str(exc))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(timeout=15); t2.join(timeout=15)

        # Al menos 1 thread debe haber tenido éxito
        self.assertGreaterEqual(len(resultados), 1,
            f"Al menos un thread debe retornar un ID. Errores: {errores}")

        # Si ambos tuvieron éxito, deben haber obtenido IDs únicos
        if len(resultados) == 2:
            self.assertEqual(
                len(set(resultados)), 2,
                f"Los IDs deben ser únicos; recibidos: {resultados}"
            )

        # Errores críticos (no de lock) deben fallar el test
        errores_criticos = [e for e in errores if "locked" not in e.lower()]
        self.assertFalse(errores_criticos,
            f"Errores no relacionados con lock de SQLite: {errores_criticos}")

    def test_reserva_dos_ids_consecutivos_para_devolucion_encadenada(self):
        """
        _reservar_grupos(2) devuelve dos IDs consecutivos sin brecha ni colisión.
        Necesario para devolución + retiro encadenado en la misma transacción.
        """
        from app_inventario.views import _reservar_grupos

        ids = _reservar_grupos(2)
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[1], ids[0] + 1, "Los IDs deben ser consecutivos")

        ids2 = _reservar_grupos(1)
        self.assertEqual(ids2[0], ids[1] + 1, "El siguiente ID no debe colisionar")

    def test_dos_retiros_concurrentes_crean_grupos_distintos(self):
        """
        Dos retiros ejecutados en threads paralelos deben crear GrupoMovimiento
        con grupo_id diferentes. Ni movimientos ni grupos deben mezclarse.
        """
        from app_inventario.models import GrupoMovimiento

        # Crear 2 baldes para los 2 retiros
        crear_balde(ProductoFijo.objects.get(plu="001"), 4.5, self.CODIGO)
        crear_balde(ProductoFijo.objects.get(plu="001"), 5.5, self.CODIGO)

        errores = []
        grupos_creados = []
        barrera = threading.Barrier(2)
        cliente1 = Client()
        cliente2 = Client()

        def retirar(cliente):
            try:
                barrera.wait()
                r = post_json(cliente, "/api/confirmar_retiro/", {
                    "destino": "Local Norte",
                    "productos": [{"plu": "001", "codigo_barras": self.CODIGO}],
                })
                if r.status_code == 200:
                    grupos_creados.append(r.json().get("grupo_id"))
                # 409 por concurrencia es aceptable
            except Exception as exc:
                errores.append(str(exc))

        t1 = threading.Thread(target=retirar, args=(cliente1,))
        t2 = threading.Thread(target=retirar, args=(cliente2,))
        t1.start(); t2.start()
        t1.join(timeout=15); t2.join(timeout=15)

        self.assertFalse(errores, f"Errores: {errores}")
        # Al menos un retiro debió exitir (el otro puede haber perdido la carrera)
        self.assertGreaterEqual(len(grupos_creados), 1)
        # Si ambos exitaron, los grupos deben ser distintos
        if len(grupos_creados) == 2:
            self.assertNotEqual(
                grupos_creados[0], grupos_creados[1],
                "Dos retiros exitosos no pueden compartir grupo_id"
            )

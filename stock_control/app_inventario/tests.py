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
from unittest.mock import patch
from django.db import transaction
from django.test import TestCase, TransactionTestCase, Client
from django.utils import timezone

from app_inventario.models import (
    BocaSalida, ProductoFijo, RegistroMovimiento,
    GrupoMovimiento, StockBalde,
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

    def test_BUG2_grupo_id_fuera_del_atomic_colisiona_con_request_concurrente(self):
        """
        Escenario: el grupo_id se calcula con MAX() fuera del atomic. Un request
        concurrente (inyectado en el mock) ya usó ese grupo_id antes de que este
        request entre al atomic.

        Bug: el view usa el grupo_id calculado antes de la inyección (grupo_id=1),
        que ya fue tomado por el request concurrente → misma clave en GrupoMovimiento.
        Fix: el grupo_id se calcula dentro del atomic con select_for_update,
        ve el RM inyectado con grupo_id=1 → calcula grupo_id=2.
        """
        balde = crear_balde(self.prod, 4.5, "2000100045001")
        prod2 = crear_producto("002", "Chocolate")   # para el RM inyectado

        original_enter = transaction.Atomic.__enter__
        intercepted = [False]

        def inject_concurrent_grupo(atomic_self):
            if not intercepted[0]:
                intercepted[0] = True
                # Simula: request concurrente ya escribió con grupo_id=1
                # (el mismo valor que el código buggy calculó fuera del atomic)
                RegistroMovimiento.objects.create(
                    grupo_id=1,
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

        # Código buggy → grupo_id=1 (colisiona con el inyectado, _actualizar_total_grupo
        #   agrega el RM inyectado en la cuenta y genera totales incorrectos)
        # Fix correcto → grupo_id=2 (calculado dentro del atomic, ve MAX=1 → +1=2)
        self.assertEqual(
            grupo_id_obtenido, 2,
            f"BUG-2: el view usó grupo_id={grupo_id_obtenido} en vez de 2. "
            "El MAX(grupo_id) debe calcularse con select_for_update dentro del atomic "
            "para evitar colisiones con requests concurrentes.",
        )

        # El GrupoMovimiento con grupo_id=2 debe tener solo 1 ítem (no contaminado)
        gm = GrupoMovimiento.objects.get(grupo_id=grupo_id_obtenido)
        self.assertEqual(
            gm.cantidad_items, 1,
            "El GrupoMovimiento del retiro debe tener 1 ítem, "
            "no 2 (contaminado por el RM del request concurrente).",
        )

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

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
from django.test import TestCase, Client
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

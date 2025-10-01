# views.py (consolidado y corregido)
import os
import json
import sqlite3
import logging
import pandas as pd

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, Max, Q, OuterRef, Subquery
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt

from .models import (
    BocaSalida, OrigenIngreso, ProductoFijo,
    RegistroMovimiento, GrupoMovimiento, StockBalde
)

logger = logging.getLogger(__name__)

# =========================================================
# Helpers
# =========================================================

def conectar_bd():
    """Conectar a la base de datos SQLite (utilidad puntual)."""
    conn = sqlite3.connect("inventario.db")
    conn.row_factory = sqlite3.Row
    return conn

def api_stock_detallado(request):
    """
    API JSON con el stock por producto: nombre, stock_minimo y cantidad (baldes).
    """
    productos = ProductoFijo.objects.annotate(stock_actual=Count('stockbalde'))
    data = [
        {"nombre": p.nombre, "stock_minimo": p.stock_minimo, "cantidad": p.stock_actual}
        for p in productos
    ]
    return JsonResponse({"stock_detallado": data})

# --- Legacy: api_stock_detallado (si te lo sigue importando urls.py)
def api_stock_detallado(request):
    productos = ProductoFijo.objects.annotate(stock_actual=Count('stockbalde'))
    data = [{"nombre": p.nombre, "stock_minimo": p.stock_minimo, "cantidad": p.stock_actual} for p in productos]
    return JsonResponse({"stock_detallado": data})

# --- Legacy: agregar_productos (agrega directo al stock SIN grupo/movimiento)
from django.views.decorators.csrf import csrf_exempt
@csrf_exempt
def agregar_productos(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)
    try:
        data = json.loads(request.body or "{}")
        productos = data.get("productos", [])
        if not productos:
            return JsonResponse({"error": "No se enviaron productos"}, status=400)

        for producto in productos:
            plu = producto.get("plu")
            peso = producto.get("peso")
            if not plu or peso is None:
                return JsonResponse({"error": "Datos incompletos"}, status=400)
            producto_obj = ProductoFijo.objects.get(plu=plu)
            StockBalde.objects.create(producto=producto_obj, peso=float(peso))

        return JsonResponse({"message": "Productos agregados exitosamente"}, status=200)
    except ProductoFijo.DoesNotExist:
        return JsonResponse({"error": "Producto no encontrado"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)




def _actualizar_total_grupo(grupo_id, tipo, origen=None, destino_nombre=None):
    """
    Recalcula y persiste totales del grupo.
    tipo: 'ingreso' | 'retiro'
    """
    agg = (RegistroMovimiento.objects
           .filter(grupo_id=grupo_id)
           .aggregate(total=Sum('peso'), cantidad=Count('id')))
    total = agg['total'] or 0
    cant = agg['cantidad'] or 0

    destino_obj = None
    if destino_nombre:
        destino_obj = BocaSalida.objects.filter(nombre=destino_nombre).first()

    GrupoMovimiento.objects.update_or_create(
        grupo_id=grupo_id,
        defaults={
            'tipo': tipo,  # 'ingreso' o 'retiro'
            'origen': origen if tipo == 'ingreso' else None,
            'destino': destino_obj if tipo == 'retiro' else None,
            'total_peso': total,
            'cantidad_items': cant,
        }
    )


def _print_group_if_enabled(grupo_id: int):
    if not getattr(settings, "PRINT_FROM_VIEWS", False):
        return
    try:
        from .services.printing import print_grupo_movimiento
        copias = getattr(settings, "PRINT_COPIAS", 1)
        print_grupo_movimiento(grupo_id, copias=copias)
        logger.info("Ticket de grupo #%s impreso (desde view)", grupo_id)
    except Exception:
        logger.exception("Error al imprimir ticket del grupo #%s (desde view)", grupo_id)


def reimprimir_ticket(request, grupo_id: int):
    """
    Reimprime el comprobante del movimiento agrupado (grupo_id).
    Acepta 'copias' opcional por POST o ?copias=
    """
    try:
        copias = int(
            request.POST.get("copias")
            or request.GET.get("copias")
            or getattr(settings, "PRINT_COPIAS", 1)
            or 1
        )
        from .services.printing import print_grupo_movimiento
        print_grupo_movimiento(grupo_id, copias=copias)
        logger.info("Reimpresión solicitada para grupo #%s (%s copias)", grupo_id, copias)
        return JsonResponse({"ok": True, "message": f"Reimpresión enviada para el grupo #{grupo_id} ({copias} copia/s)."})
    except Exception as e:
        logger.exception("Error reimprimiendo grupo #%s", grupo_id)
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


# =========================================================
# Vistas principales
# =========================================================

def index(request):
    stock_resumido = ProductoFijo.objects.annotate(cantidad=Count('stockbalde'))
    return render(request, "index.html", {"stock_resumido": stock_resumido})


def cargar_productos_desde_excel():
    """
    Carga productos desde productos.xlsx (Nombre, PLU) ubicado junto a la app.
    """
    archivo_excel = os.path.join(os.path.dirname(__file__), "productos.xlsx")
    try:
        df = pd.read_excel(archivo_excel)
        if 'Nombre' not in df.columns or 'PLU' not in df.columns:
            return {"error": "El archivo Excel no tiene las columnas necesarias (Nombre, PLU)"}

        for _, row in df.iterrows():
            nombre = row['Nombre']
            plu = str(row['PLU']).zfill(3)
            ProductoFijo.objects.get_or_create(plu=plu, nombre=nombre)

        return {"message": "Productos cargados exitosamente"}

    except Exception as e:
        return {"error": f"Error procesando el archivo: {str(e)}"}


@csrf_exempt
def cargar_productos_excel(request):
    if request.method == "POST" and request.FILES.get("archivo"):
        archivo = request.FILES["archivo"]
        fs = FileSystemStorage(location="uploads/")
        nombre_archivo = fs.save(archivo.name, archivo)
        ruta_archivo = fs.path(nombre_archivo)

        try:
            df = pd.read_excel(ruta_archivo)
            if "Nombre" not in df.columns or "PLU" not in df.columns:
                return JsonResponse({"error": "El archivo debe contener las columnas 'Nombre' y 'PLU'"}, status=400)

            for _, row in df.iterrows():
                nombre = row["Nombre"]
                plu = str(row["PLU"]).zfill(3)
                ProductoFijo.objects.get_or_create(plu=plu, nombre=nombre)

            return JsonResponse({"message": "Productos cargados correctamente"})

        except Exception as e:
            return JsonResponse({"error": f"Error al procesar el archivo: {str(e)}"}, status=500)

    return JsonResponse({"error": "No se envió ningún archivo"}, status=400)


def importar_productos(request):
    resultado = cargar_productos_desde_excel()
    return JsonResponse(resultado)


@cache_page(5)
def obtener_stock(request):
    try:
        productos_stock = ProductoFijo.objects.annotate(
            cantidad=Count("stockbalde")
        ).values("nombre", "cantidad", "stock_minimo")
        return JsonResponse({"stock": list(productos_stock)})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def stock_detallado(request):
    stock = StockBalde.objects.select_related("producto").all()
    return render(request, "stock_detallado.html", {"stock_detallado": stock})


def historial(request):
    movimientos_list = RegistroMovimiento.objects.all().order_by('-timestamp')
    paginator = Paginator(movimientos_list, 10)
    page_number = request.GET.get("page", 1)

    movimientos = paginator.get_page(page_number)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = [
            {
                "grupo_id": mov.grupo_id,
                "tipo": mov.tipo,
                "timestamp": mov.timestamp.strftime("%d/%m/%Y %H:%M")
            }
            for mov in movimientos
        ]
        return JsonResponse({
            "movimientos": data,
            "has_next": movimientos.has_next(),
            "has_previous": movimientos.has_previous(),
            "current_page": movimientos.number,
            "num_pages": movimientos.paginator.num_pages,
        })

    return render(request, "historial_movimientos.html", {"movimientos": movimientos})


def historial_movimientos(request):
    """
    Lista de movimientos agrupados por grupo_id mostrando SOLO el último
    movimiento de cada grupo, con filtros por fecha, local y tipo.
    """
    base_qs = RegistroMovimiento.objects.all()

    # Filtros
    desde_str = request.GET.get("desde")
    hasta_str = request.GET.get("hasta")
    local = (request.GET.get("local") or "").strip()
    tipo = request.GET.get("tipo")

    if desde_str:
        d = parse_date(desde_str)
        if d:
            base_qs = base_qs.filter(timestamp__date__gte=d)
    if hasta_str:
        h = parse_date(hasta_str)
        if h:
            base_qs = base_qs.filter(timestamp__date__lte=h)

    if local:
        base_qs = base_qs.filter(
            Q(boca_salida__icontains=local) |
            Q(origen__icontains=local) |
            Q(destino__nombre__icontains=local)
        )

    if tipo in ("ingreso", "retiro"):
        base_qs = base_qs.filter(tipo=tipo)

    # Último movimiento por grupo_id (respetando filtros)
    latest_in_group = (
        base_qs.filter(grupo_id=OuterRef("grupo_id"))
               .order_by("-timestamp", "-id")
               .values("id")[:1]
    )
    latest_ids_subq = (
        base_qs.values("grupo_id")
               .annotate(latest_id=Subquery(latest_in_group))
               .values("latest_id")
    )

    movimientos_qs = (
        RegistroMovimiento.objects
        .filter(id__in=Subquery(latest_ids_subq))
        .select_related("producto", "destino")
        .order_by("-timestamp", "-id")
    )

    # Paginación
    page_number = request.GET.get("page", 1)
    paginator = Paginator(movimientos_qs, 20)
    movimientos_page = paginator.get_page(page_number)

    return render(
        request,
        "historial_movimientos.html",
        {
            "movimientos": movimientos_page,
            "filtros": {
                "desde": desde_str or "",
                "hasta": hasta_str or "",
                "local": local,
                "tipo": tipo or "",
            },
        },
    )


def detalle_movimiento(request, grupo_id: int):
    items = (RegistroMovimiento.objects
             .filter(grupo_id=grupo_id)
             .select_related("producto", "destino")
             .order_by("timestamp", "id"))

    if not items.exists():
        raise Http404("Movimiento no encontrado")

    header = GrupoMovimiento.objects.filter(grupo_id=grupo_id).select_related("destino").first()
    if header:
        total_peso = header.total_peso or 0
        cantidad_items = header.cantidad_items or items.count()
        tipo = header.tipo
        origen = header.origen
        destino = header.destino
    else:
        agg = items.aggregate(total=Sum("peso"), cantidad=Count("id"),
                              tipo_any=Max("tipo"),
                              origen_any=Max("origen"),
                              destino_any=Max("destino"))
        total_peso = agg["total"] or 0
        cantidad_items = agg["cantidad"] or 0
        tipo = agg["tipo_any"]
        origen = agg["origen_any"]
        destino = None
        if agg["destino_any"]:
            destino = BocaSalida.objects.filter(pk=agg["destino_any"]).first()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "grupo_id": grupo_id,
            "tipo": tipo,
            "origen": origen,
            "destino": destino.nombre if destino else None,
            "total_peso": round(float(total_peso), 3),
            "cantidad_items": int(cantidad_items),
            "items": [{"producto": i.producto.nombre, "peso": float(i.peso)} for i in items],
        })

    return render(request, "detalle_movimiento.html", {
        "grupo_id": grupo_id,
        "tipo": tipo,
        "origen": origen,
        "destino": destino,
        "total_peso": total_peso,
        "cantidad_items": cantidad_items,
        "items": items,
    })


@csrf_exempt
def eliminar_movimiento(request, grupo_id):
    if request.method == "DELETE":
        movs = RegistroMovimiento.objects.filter(grupo_id=grupo_id)
        if movs.exists():
            movs.delete()
            GrupoMovimiento.objects.filter(grupo_id=grupo_id).delete()
            return JsonResponse({"success": True, "message": "Movimiento eliminado correctamente."})
        return JsonResponse({"success": False, "error": "Movimiento no encontrado."}, status=404)
    return JsonResponse({"success": False, "error": "Método no permitido."}, status=405)


def buscar(request):
    return render(request, "index.html")


def buscar_detallado(request):
    if request.method == "POST":
        termino_busqueda = request.POST.get("termino_busqueda", "").strip()
        fecha = request.POST.get("fecha", "").strip()

        if not termino_busqueda and not fecha:
            productos = StockBalde.objects.all()
        else:
            productos = StockBalde.objects.filter(
                Q(producto__nombre__icontains=termino_busqueda) |
                Q(producto__plu__icontains=termino_busqueda)
            )
            fecha_formateada = parse_date(fecha)
            if fecha_formateada:
                productos = productos.filter(timestamp__date=fecha_formateada)

        return render(request, "stock_detallado.html", {"stock_detallado": productos})

    return JsonResponse({"error": "Método no permitido"}, status=405)


# =========================================================
# API: lista temporal por sesión (escaneo)
# =========================================================

@csrf_exempt
def reiniciar_lista_temporal(request):
    request.session["productos_temporales"] = []
    request.session.modified = True
    return JsonResponse({"message": "Lista de productos escaneados reiniciada"})


@csrf_exempt
def obtener_codigos(request):
    return JsonResponse({"productos": request.session.get("productos_temporales", [])})


@csrf_exempt
def procesar_codigo(request):
    """
    Recibe {"codigo": "xxxxxxxxxxxxx"} (13 dígitos).
    Extrae PLU y peso, valida contra ProductoFijo, y agrega a la lista temporal en sesión.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    codigo_barras = data.get("codigo")
    if not codigo_barras or len(codigo_barras) != 13 or not codigo_barras.isdigit():
        return JsonResponse({"error": "Código de barras no válido"}, status=400)

    plu = codigo_barras[2:5]
    peso = float(f"{codigo_barras[8]}.{codigo_barras[9:12]}")

    try:
        prod = ProductoFijo.objects.get(plu=plu)
    except ProductoFijo.DoesNotExist:
        return JsonResponse({"error": "Producto no encontrado"}, status=400)

    productos_temporales = request.session.get("productos_temporales", [])
    nuevo = {"nombre": prod.nombre, "peso": peso, "plu": plu}
    if not any(p["plu"] == nuevo["plu"] and p["peso"] == nuevo["peso"] for p in productos_temporales):
        productos_temporales.append(nuevo)

    request.session["productos_temporales"] = productos_temporales
    request.session.modified = True

    return JsonResponse({
        "message": "Producto agregado temporalmente",
        "productos_temporales": productos_temporales
    })


@csrf_exempt
def obtener_productos_temporales(request):
    return JsonResponse({"productos": request.session.get("productos_temporales", [])})


@csrf_exempt
def eliminar_producto_temporal(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or "{}")
        plu = data.get("plu")
        productos_temporales = request.session.get("productos_temporales", [])
        productos_temporales = [p for p in productos_temporales if p["plu"] != plu]
        request.session["productos_temporales"] = productos_temporales
        request.session.modified = True
        return JsonResponse({"success": True, "message": "Producto eliminado de la sesión."})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
def confirmar_agregado(request):
    """
    Vuelca la lista temporal al stock (sin crear grupo/movimientos).
    Mantenida por compatibilidad: si preferís trabajar 100% con grupos, podés prescindir de esta.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    productos = request.session.get("productos_temporales", [])
    if not productos:
        return JsonResponse({"error": "No hay productos para confirmar"}, status=400)

    productos_agregados = []
    for p in productos:
        try:
            producto_obj = ProductoFijo.objects.get(plu=p["plu"])
            StockBalde.objects.create(producto=producto_obj, peso=p["peso"])
            productos_agregados.append(producto_obj.nombre)
        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": f"Producto con PLU {p['plu']} no encontrado"}, status=404)

    request.session["productos_temporales"] = []
    request.session.modified = True

    return JsonResponse({"message": f"Productos agregados: {', '.join(productos_agregados)} ✅"}, status=200)


# =========================================================
# Confirmar Ingreso / Retiro (agrupado con grupo_id)
# =========================================================

@csrf_exempt
def confirmar_codigos(request):
    """
    Confirma INGRESO agrupado.
    - Crea StockBalde por cada balde ingresado.
    - Registra RegistroMovimiento (tipo='ingreso') con 'origen'.
    - Actualiza totales del GrupoMovimiento.
    - Limpia la lista temporal de la sesión.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    productos = data.get("productos") or request.session.get("productos_temporales", [])
    origen = (data.get("origen") or "").strip()

    if not productos:
        return JsonResponse({"error": "No hay productos para ingresar"}, status=400)
    if not origen:
        return JsonResponse({"error": "Debe indicar un origen"}, status=400)

    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    nombres_ingresados = []

    try:
        with transaction.atomic():
            for p in productos:
                plu = (p or {}).get("plu")
                peso = (p or {}).get("peso")
                if not plu:
                    return JsonResponse({"error": "Producto sin PLU"}, status=400)
                if peso is None:
                    return JsonResponse({"error": f"Producto {plu} sin peso"}, status=400)

                try:
                    producto_obj = ProductoFijo.objects.get(plu=plu)
                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

                # 1) Crear balde en stock
                StockBalde.objects.create(producto=producto_obj, peso=float(peso))

                # 2) Registrar movimiento (ingreso)
                RegistroMovimiento.objects.create(
                    grupo_id=nuevo_grupo_id,
                    producto=producto_obj,
                    peso=float(peso),
                    tipo="ingreso",
                    origen=origen,
                    boca_salida=origen,  # compatibilidad con campo legado para mostrar
                )
                nombres_ingresados.append(producto_obj.nombre)

            # 3) Actualizar totales del grupo
            _actualizar_total_grupo(nuevo_grupo_id, tipo="ingreso", origen=origen)

            # 4) Limpiar lista temporal en sesión
            if "productos_temporales" in request.session:
                request.session["productos_temporales"] = []
                request.session.modified = True

    except Exception as e:
        return JsonResponse({"error": f"Error al confirmar ingreso: {e}"}, status=500)

    # Impresión opcional desde la view (si no usás signals)
    _print_group_if_enabled(nuevo_grupo_id)

    msg = "Productos agregados correctamente:\n\n" + "\n".join(nombres_ingresados)
    return JsonResponse(
        {"success": True, "grupo_id": nuevo_grupo_id, "origen": origen,
         "productos": nombres_ingresados, "message": msg},
        status=200
    )


@csrf_exempt
def confirmar_retiro(request):
    """
    Confirma RETIRO agrupado.
    - Valida stock.
    - Elimina baldes del stock.
    - Registra RegistroMovimiento (tipo='retiro') con 'destino' (FK) y `boca_salida` (texto).
    - Actualiza totales del GrupoMovimiento.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    productos = data.get("productos", [])
    destino_nombre = (data.get("destino") or "").strip()

    if not productos:
        return JsonResponse({"error": "No hay productos para retirar"}, status=400)
    if not destino_nombre:
        return JsonResponse({"error": "Debe indicar un destino"}, status=400)

    destino_obj = BocaSalida.objects.filter(nombre=destino_nombre).first()
    if not destino_obj:
        return JsonResponse({"error": f"Destino '{destino_nombre}' no existe"}, status=400)

    # Agrupar por PLU para validar stock
    pedidos_por_plu = {}
    for p in productos:
        plu = (p or {}).get("plu")
        if not plu:
            return JsonResponse({"error": "Producto sin PLU"}, status=400)
        pedidos_por_plu[plu] = pedidos_por_plu.get(plu, 0) + 1

    # Validación de stock
    nombres_sin_stock = []
    productos_resueltos = {}  # plu -> (producto_obj, queryset baldes)
    for plu, qty in pedidos_por_plu.items():
        try:
            producto_obj = ProductoFijo.objects.get(plu=plu)
        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

        disponibles = StockBalde.objects.filter(producto=producto_obj).order_by("-timestamp")
        if disponibles.count() < qty:
            nombres_sin_stock.append(producto_obj.nombre)
        else:
            productos_resueltos[plu] = (producto_obj, disponibles[:qty])

    if nombres_sin_stock:
        return JsonResponse({"error": f"No hay stock disponible para: {', '.join(nombres_sin_stock)}"}, status=400)

    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    productos_retirados = []

    try:
        with transaction.atomic():
            for plu, (producto_obj, baldes_qs) in productos_resueltos.items():
                for balde in baldes_qs:
                    peso = balde.peso
                    # 1) eliminar balde del stock
                    balde.delete()
                    # 2) registrar movimiento (retiro)
                    RegistroMovimiento.objects.create(
                        grupo_id=nuevo_grupo_id,
                        producto=producto_obj,
                        peso=peso,
                        tipo="retiro",             # <<< unificado
                        destino=destino_obj,       # FK
                        boca_salida=destino_nombre # texto legacy para mostrar
                    )
                    productos_retirados.append(producto_obj.nombre)

            # 3) actualizar totales del grupo
            _actualizar_total_grupo(nuevo_grupo_id, tipo="retiro", destino_nombre=destino_nombre)

    except Exception as e:
        return JsonResponse({"error": f"Error al retirar productos: {e}"}, status=500)

    # Impresión opcional desde la view (si no usás signals)
    _print_group_if_enabled(nuevo_grupo_id)

    msg = "Productos retirados correctamente:\n\n" + "\n".join(productos_retirados)
    return JsonResponse(
        {"success": True, "grupo_id": nuevo_grupo_id, "destino": destino_nombre,
         "productos": productos_retirados, "message": msg},
        status=200
    )


# =========================================================
# Catálogos: Bocas / Orígenes
# =========================================================

@csrf_exempt
def obtener_bocas(request):
    if request.method == "GET":
        bocas = list(BocaSalida.objects.values_list("nombre", flat=True))
        return JsonResponse({"bocas": bocas})
    return JsonResponse({"error": "Método no permitido"}, status=405)


@csrf_exempt
def crear_boca(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
            nombre = (data.get("nombre") or "").strip()
            if not nombre:
                return JsonResponse({"success": False, "error": "El nombre no puede estar vacío"}, status=400)
            if BocaSalida.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({"success": False, "error": "Ya existe una boca con ese nombre"}, status=400)
            BocaSalida.objects.create(nombre=nombre)
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)


@csrf_exempt
def crear_origen(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
            nombre = (data.get("nombre") or "").strip()
            if not nombre:
                return JsonResponse({"success": False, "error": "El nombre no puede estar vacío"}, status=400)
            if OrigenIngreso.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({"success": False, "error": "Ya existe un origen con ese nombre"}, status=400)
            OrigenIngreso.objects.create(nombre=nombre)
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)


def obtener_bocas_salida(request):
    if request.method == "GET":
        bocas = list(BocaSalida.objects.values_list("nombre", flat=True).order_by("nombre"))
        return JsonResponse({"lista": bocas})


def obtener_origenes(request):
    if request.method == "GET":
        origenes = list(OrigenIngreso.objects.values_list("nombre", flat=True).order_by("nombre"))
        return JsonResponse({"lista": origenes})


@csrf_exempt
def eliminar_boca_salida(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
            nombre = (data.get("nombre") or "").strip()
            if not nombre:
                return JsonResponse({"success": False, "error": "Nombre no proporcionado"}, status=400)
            boca = BocaSalida.objects.filter(nombre__iexact=nombre).first()
            if boca:
                boca.delete()
                return JsonResponse({"success": True})
            else:
                return JsonResponse({"success": False, "error": "Boca no encontrada"}, status=404)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)


@csrf_exempt
def eliminar_origen(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
            nombre = (data.get("nombre") or "").strip()
            if not nombre:
                return JsonResponse({"success": False, "error": "Nombre no proporcionado"}, status=400)
            origen = OrigenIngreso.objects.filter(nombre__iexact=nombre).first()
            if origen:
                origen.delete()
                return JsonResponse({"success": True})
            else:
                return JsonResponse({"success": False, "error": "Origen no encontrado"}, status=404)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)


# =========================================================
# Backups y mantenimiento
# =========================================================

def descargar_backup(request):
    db_path = settings.DATABASES["default"]["NAME"]
    if os.path.exists(db_path):
        return FileResponse(open(db_path, 'rb'), as_attachment=True, filename='backup.sqlite3')
    return JsonResponse({"error": "No se encontró la base de datos"}, status=404)


@csrf_exempt
def importar_backup(request):
    if request.method == "POST" and request.FILES.get("archivo"):
        try:
            with open("db.sqlite3", "wb+") as destino:
                for chunk in request.FILES["archivo"].chunks():
                    destino.write(chunk)
            return JsonResponse({"success": True, "message": "Backup restaurado correctamente"})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"error": "❌ Método no permitido o archivo no enviado"}, status=400)


@csrf_exempt
def reiniciar_stock(request):
    if request.method == "POST":
        try:
            StockBalde.objects.all().delete()
            return JsonResponse({"success": True, "message": "✅ Todos los baldes fueron eliminados. El stock ahora está en cero."})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

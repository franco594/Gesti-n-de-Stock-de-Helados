# views.py (consolidado y corregido)
import time
from django.utils import timezone
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
from django.core.management import call_command 


from .models import (
    BocaSalida, OrigenIngreso, ProductoFijo,
    RegistroMovimiento, GrupoMovimiento, StockBalde
)
from app_inventario import models

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


def actualizar_stock_minimo(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "JSON inválido"}, status=400)

    productos = data.get("productos", [])
    if not isinstance(productos, list):
        return JsonResponse({"success": False, "error": "'productos' debe ser una lista"}, status=400)

    actualizados = 0
    for producto in productos:                       # <— usá SIEMPRE el mismo nombre
        plu = producto.get("plu")
        minimo = producto.get("stock_minimo")
        if plu is None or minimo is None:
            continue
        actualizados += (
            ProductoFijo.objects
            .filter(plu=plu)
            .update(stock_minimo=minimo)
        )

    return JsonResponse({"success": True, "message": "OK", "actualizados": actualizados}, status=200)


def _actualizar_total_grupo(grupo_id, tipo, origen=None, destino_nombre=None):
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
            'tipo': tipo,
            'origen': origen if tipo == 'ingreso' else None,
            'destino': destino_obj if tipo == 'salida' else None,
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
    stock_resumido = ProductoFijo.objects.annotate(
        cantidad=Count('stockbalde', filter=Q(stockbalde__is_activo=True))
    )
    # 👇 NUEVO
    tot_balde = StockBalde.objects.filter(is_activo=True).count()
    tot_kilos = StockBalde.objects.filter(is_activo=True).aggregate(s=Sum('peso'))['s'] or 0

    return render(request, "index.html", {
        "stock_resumido": stock_resumido,
        "total_baldes": tot_balde,
        "total_kilos": round(float(tot_kilos), 2),
    })


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
    tipo = (request.GET.get("tipo") or "").strip().lower()
    gusto = (request.GET.get("gusto") or "").strip()     # nombre del gusto a buscar
    codigo = (request.GET.get("codigo") or "").strip()   # EAN-13 exacto o substring

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

    if tipo:
        if tipo in ("retiro", "salida"):
            # Incluir ambos para compatibilidad histórica
            base_qs = base_qs.filter(tipo__in=["retiro", "salida"])
        elif tipo == "ingreso":
            base_qs = base_qs.filter(tipo="ingreso")
        else:
            # cualquier otro valor ignora el filtro de tipo
            pass

    if gusto:
        base_qs = base_qs.filter(producto__nombre__icontains=gusto)
    if codigo:
        # si queremos exacto: codigo_barras=codigo
        # si queremos "contiene": codigo_barras__icontains=codigo
        base_qs = base_qs.filter(codigo_barras__icontains=codigo)

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

    # Total global (todos los resultados filtrados, sin paginar)
    total_kg_global = base_qs.aggregate(s=Sum("peso"))["s"] or 0

    # Paginación
    page_number = request.GET.get("page", 1)
    paginator = Paginator(movimientos_qs, 20)
    movimientos_page = paginator.get_page(page_number)

    # === NUEVO: total de kilos de los movimientos que se muestran en esta página ===


    # ids de grupo visibles en la página actual
    grupo_ids_visibles = [m.grupo_id for m in movimientos_page.object_list]

    # primero intentamos sumar desde GrupoMovimiento (siempre que exista el header)
    total_kg = (
        GrupoMovimiento.objects
        .filter(grupo_id__in=grupo_ids_visibles)
        .aggregate(s=Sum("total_peso"))["s"] or 0
    )

    # fallback: si algún grupo no tiene header, sumamos su peso desde RegistroMovimiento
    grupos_con_header = set(
        GrupoMovimiento.objects
        .filter(grupo_id__in=grupo_ids_visibles)
        .values_list("grupo_id", flat=True)
    )
    faltantes = set(grupo_ids_visibles) - grupos_con_header
    if faltantes:
        total_faltantes = (
            RegistroMovimiento.objects
            .filter(grupo_id__in=faltantes)
            .aggregate(s=Sum("peso"))["s"] or 0
        )
        total_kg += total_faltantes

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
        "total_kg_global": total_kg_global,   # 👈 NUEVO: total global filtrado
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
            "total_peso": round(float(total_peso), 2),
            "cantidad_items": int(cantidad_items),
            "items": [
                {
                    "producto": i.producto.nombre,
                    "peso": float(i.peso),
                    "codigo_barras": getattr(i, "codigo_barras", None)  # 👈 nuevo
                }
                for i in items
            ],
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
    Recibe {"codigo": "xxxxxxxxxxxxx"} (EAN-13).
    - Extrae PLU (3 dígitos) y peso (X.XXX) del código.
    - Verifica que el producto exista.
    - Agrega a la lista temporal en sesión incluyendo `codigo_barras`.
    - Evita duplicados por el mismo `codigo_barras`.
    Responde con la lista temporal actualizada.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # --- Parseo de body ---
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    codigo_barras = (data.get("codigo") or "").strip()

    # Validación básica de EAN-13 (longitud y dígitos)
    if not (len(codigo_barras) == 13 and codigo_barras.isdigit()):
        return JsonResponse({"error": "Código de barras no válido"}, status=400)

    # --- Interpretación del código ---
    plu = codigo_barras[2:5]  # 3 dígitos
    peso = float(f"{codigo_barras[8]}.{codigo_barras[9:12]}")  # X.XXX

    # --- Producto existente ---
    try:
        prod = ProductoFijo.objects.get(plu=plu)
    except ProductoFijo.DoesNotExist:
        return JsonResponse({"error": "Producto no encontrado"}, status=400)

    # --- Lista temporal en sesión ---
    productos_temporales = request.session.get("productos_temporales", [])

    # Armamos el item incluyendo el código de barras
    nuevo = {
        "nombre": prod.nombre,
        "peso": peso,
        "plu": plu,
        "codigo_barras": codigo_barras,  # 👈 clave nueva para trazabilidad
    }

    # Evitar duplicados: si ya existe ese mismo código en la lista, no lo agregamos
    if not any(p.get("codigo_barras") == codigo_barras for p in productos_temporales):
        productos_temporales.append(nuevo)

    # Persistir en sesión
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
    Confirma un INGRESO de baldes con trazabilidad por código de barras.
    - Requiere para cada item: {plu, nombre?, peso, codigo_barras}
    - Bloquea duplicados: si un codigo_barras ya existe, rechaza.
    - Crea StockBalde (is_activo=True) y RegistroMovimiento (tipo='ingreso').
    - Agrupa todo en un nuevo grupo_id y actualiza GrupoMovimiento.
    - Limpia la lista temporal en sesión si existe.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # --- Parseo payload ---
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    productos = data.get("productos", []) or request.session.get("productos_temporales", [])
    origen = (data.get("origen") or "").strip()

    if not productos:
        return JsonResponse({"error": "No hay productos para ingresar"}, status=400)
    if not origen:
        return JsonResponse({"error": "Debe indicar un origen"}, status=400)

    # --- Nuevo grupo ---
    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    ingresados = []

    try:
        with transaction.atomic():
            for p in productos:
                plu = (p or {}).get("plu")
                peso = (p or {}).get("peso")
                codigo_barras = (p or {}).get("codigo_barras") or (p or {}).get("codigo")

                # Validaciones
                if not plu:
                    return JsonResponse({"error": "Producto sin PLU"}, status=400)
                if not peso:
                    return JsonResponse({"error": f"Producto {plu} sin peso"}, status=400)
                if not codigo_barras or len(str(codigo_barras)) != 13:
                    return JsonResponse({"error": "Cada balde debe incluir 'codigo_barras' de 13 dígitos"}, status=400)

                # Producto
                try:
                    producto_obj = ProductoFijo.objects.get(plu=plu)
                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

                # Duplicado (anti-reingreso solo si hay uno ACTIVO)
                if StockBalde.objects.filter(codigo_barras=codigo_barras, is_activo=True).exists():
                    return JsonResponse(
                        {"error": f"El balde {codigo_barras} ya fue ingresado previamente y sigue activo"},
                        status=409  # Conflict
                    )

                # Crear balde activo
                StockBalde.objects.create(
                    producto=producto_obj,
                    peso=float(peso),
                    codigo_barras=codigo_barras,
                    is_activo=True,
                    fecha_retiro=None,
                )

                # Crear movimiento
                RegistroMovimiento.objects.create(
                    grupo_id=nuevo_grupo_id,
                    producto=producto_obj,
                    peso=float(peso),
                    tipo="ingreso",
                    origen=origen,
                    boca_salida=origen,  # compatibilidad
                    codigo_barras=codigo_barras,
                )

                ingresados.append(producto_obj.nombre)

            # Totales del grupo
            _actualizar_total_grupo(nuevo_grupo_id, tipo="ingreso", origen=origen)

            # Limpiar sesión temporal
            if "productos_temporales" in request.session:
                request.session["productos_temporales"] = []
                request.session.modified = True

    except Exception as e:
        return JsonResponse({"error": f"Error al confirmar ingreso: {e}"}, status=500)
    
    msg = "Productos agregados correctamente:\n\n" + "\n".join(ingresados)

    return JsonResponse({
        "success": True,
        "grupo_id": nuevo_grupo_id,
        "origen": origen,
        "productos": ingresados,
        "message": msg
    }, status=200)

@csrf_exempt
def confirmar_retiro(request):
    """
    Confirma RETIRO de baldes. Soporta trazabilidad por código y stock legacy (sin código).

    Flags opcionales en el body:
      - allow_fallback_legacy (bool, default True): si se envía un código y no existe ese balde,
        permite caer a un balde legacy (sin código) del mismo PLU.
      - legacy_ok (bool, default True): permite retirar sin enviar código (toma legacy preferentemente).
      - legacy_only (bool, default False): si no se envía código, exige que el balde retirado sea legacy.
        (implica legacy_ok=True)
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # -------- Parseo body --------
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    productos = data.get("productos", [])
    destino_nombre = (data.get("destino") or "").strip()

    # Flags de control (con defaults seguros)
    allow_fallback_legacy = bool(data.get("allow_fallback_legacy", True))
    legacy_ok = bool(data.get("legacy_ok", True))
    legacy_only = bool(data.get("legacy_only", False))
    if legacy_only:
        legacy_ok = True  # "solo legacy" implica permitir legacy

    if not productos:
        return JsonResponse({"error": "No hay productos para retirar"}, status=400)
    if not destino_nombre:
        return JsonResponse({"error": "Debe indicar un destino"}, status=400)

    # -------- Destino (FK) --------
    destino_obj = BocaSalida.objects.filter(nombre=destino_nombre).first()
    if not destino_obj:
        return JsonResponse({"error": f"Destino '{destino_nombre}' no existe"}, status=400)

    # -------- Normalizar solicitudes [(plu, codigo|None)] --------
    solicitudes = []
    for p in productos:
        plu = (p or {}).get("plu")
        if not plu:
            return JsonResponse({"error": "Producto sin PLU"}, status=400)
        codigo = (p.get("codigo") or p.get("codigo_barras") or "").strip() or None
        solicitudes.append((plu, codigo))

    # -------- Selección de baldes respetando fallback a legacy --------
    seleccionados = []  # [(producto_obj, balde), ...]
    faltantes = []

    for plu, codigo in solicitudes:
        try:
            producto_obj = ProductoFijo.objects.get(plu=plu)
        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

        base = (
            StockBalde.objects
            .filter(producto=producto_obj, is_activo=True)
            .order_by("-timestamp", "-id")
        )

        balde = None
        if codigo:
            # 1) Intento exacto por código
            balde = base.filter(codigo_barras=codigo).first()

            # 2) Si no hay ese código y se permite fallback, tomar legacy si lo hay
            if not balde and allow_fallback_legacy:
                balde_legacy = base.filter(Q(codigo_barras__isnull=True) | Q(codigo_barras="")).first()
                if balde_legacy:
                    balde = balde_legacy

            # 3) (opcional) si tampoco hay legacy y no estamos en "solo legacy", tomar cualquiera activo
            if not balde and allow_fallback_legacy and not legacy_only:
                balde = base.first()
        else:
            # No se envió código
            if not legacy_ok:
                faltantes.append(f"{producto_obj.nombre} (requiere código)")
            else:
                # Preferir legacy primero
                balde = base.filter(Q(codigo_barras__isnull=True) | Q(codigo_barras="")).first()
                if not balde and not legacy_only:
                    balde = base.first()

        if not balde:
            # No se encontró balde elegible
            if codigo:
                faltantes.append(f"{producto_obj.nombre} ({codigo})")
            else:
                faltantes.append(producto_obj.nombre)
        else:
            seleccionados.append((producto_obj, balde))

    if faltantes:
        return JsonResponse({"error": f"No hay stock disponible para: {', '.join(faltantes)}"}, status=400)

    # -------- Nuevo grupo_id --------
    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    # -------- Ejecutar retiro --------
    productos_retirados = []
    try:
        with transaction.atomic():
            for producto_obj, balde in seleccionados:
                # Soft-delete: marcar inactivo
                balde.is_activo = False
                balde.save(update_fields=["is_activo"])

                # Registrar movimiento
                RegistroMovimiento.objects.create(
                    grupo_id=nuevo_grupo_id,
                    producto=producto_obj,
                    peso=balde.peso,
                    tipo="salida",
                    destino=destino_obj,
                    boca_salida=destino_nombre,                 # compatibilidad texto
                    codigo_barras=(balde.codigo_barras or ""),  # legacy: queda vacío
                )
                productos_retirados.append(producto_obj.nombre)

            # Totales del grupo
            _actualizar_total_grupo(
                nuevo_grupo_id,
                tipo="salida",
                destino_nombre=destino_nombre
            )

    except Exception as e:
        return JsonResponse({"error": f"Error al retirar productos: {e}"}, status=500)

    msg = "Productos retirados correctamente:\n\n" + "\n".join(productos_retirados)
    return JsonResponse(
        {
            "success": True,
            "grupo_id": nuevo_grupo_id,
            "destino": destino_nombre,
            "productos": productos_retirados,
            "message": msg
        },
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

# views.py
import tempfile
from django.db import connection

def descargar_backup(request):
    """
    Descarga la base actual como backup.sqlite3 (con nombre con fecha).
    """
    db_path = settings.DATABASES["default"]["NAME"]
    if not os.path.exists(db_path):
        return JsonResponse({"error": "No se encontró la base de datos"}, status=404)

    # nombre con timestamp (opcional)
    from datetime import datetime
    fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
    return FileResponse(open(db_path, 'rb'), as_attachment=True, filename=fname)



# views.py
@csrf_exempt
def importar_backup(request):
    """
    Sube un backup .sqlite3 y reemplaza la DB de forma segura:
    - guarda a un archivo temporal
    - cierra conexiones
    - reemplaza atómicamente
    - corre migraciones (sin run_syncdb)
    """
    if request.method != "POST" or "archivo" not in request.FILES:
        return JsonResponse({"error": "❌ Método no permitido o archivo no enviado"}, status=400)

    up = request.FILES["archivo"]

    # Validaciones básicas
    if not up.name.lower().endswith(".sqlite3"):
        return JsonResponse({"success": False, "error": "El archivo debe ser .sqlite3"}, status=400)
    if up.size and up.size > 50 * 1024 * 1024:  # 50 MB
        return JsonResponse({"success": False, "error": "El archivo es demasiado grande"}, status=400)

    db_path = settings.DATABASES["default"]["NAME"]
    db_dir = os.path.dirname(db_path) or "."

    # 1) Escribir a un archivo temporal
    os.makedirs(db_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".sqlite3", dir=db_dir)
    os.close(fd)

    try:
        with open(tmp_path, "wb") as destino:
            for chunk in up.chunks():
                destino.write(chunk)

        # 2) Cerrar conexiones actuales
        connection.close()

        # 3) Backup previo opcional (por si querés volver atrás)
        prev_backup = None
        if os.path.exists(db_path):
            prev_backup = db_path + ".prev"
            try:
                if os.path.exists(prev_backup):
                    os.remove(prev_backup)
            except Exception:
                pass
            try:
                os.replace(db_path, prev_backup)
            except Exception:
                prev_backup = None  # si falla, seguimos sin .prev

        # 4) Reemplazo atómico por el nuevo archivo
        os.replace(tmp_path, db_path)

        # 5) Migraciones (sin run_syncdb)
        try:
            # Asegura que Django reabra la conexión contra la DB nueva
            connection.close()
            call_command("migrate", interactive=False, verbosity=0)
        except Exception as mig_e:
            # No abortamos: normalmente no hace falta si el backup ya estaba migrado
            print(f"[importar_backup] Warning al migrar: {mig_e}")

        # 6) Parche mínimo por SQL si faltara is_activo (defensivo)
        try:
            with connection.cursor() as c:
                c.execute("PRAGMA table_info(app_inventario_stockbalde);")
                cols = [r[1] for r in c.fetchall()]
                if "is_activo" not in cols:
                    c.execute(
                        "ALTER TABLE app_inventario_stockbalde "
                        "ADD COLUMN is_activo INTEGER NOT NULL DEFAULT 1;"
                    )
                    c.execute(
                        "CREATE INDEX IF NOT EXISTS stockbalde_is_activo_idx "
                        "ON app_inventario_stockbalde(is_activo);"
                    )
        except Exception as patch_e:
            print(f"[importar_backup] Warning al parchear is_activo: {patch_e}")

        return JsonResponse({"success": True, "message": "Backup restaurado correctamente"})

    except Exception as e:
        # Limpieza si algo falla
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return JsonResponse({"success": False, "error": str(e)}, status=500)





@csrf_exempt
def reiniciar_stock(request):
    if request.method == "POST":
        try:
            StockBalde.objects.all().delete()
            return JsonResponse({"success": True, "message": "✅ Todos los baldes fueron eliminados. El stock ahora está en cero."})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)
    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

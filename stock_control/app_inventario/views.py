# views.py (consolidado y corregido)
import time
from django.utils import timezone
import os
import json
import sqlite3
import logging
import pandas as pd

from io import BytesIO
from django.http import HttpResponse
from datetime import datetime


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

from app_inventario.services.printing import print_stock_total 



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

# --- API CRUD PRODUCTOS

@csrf_exempt
def api_listar_productos(request):
    if request.method != "GET":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    productos = ProductoFijo.objects.all().order_by("nombre")

    data = [
        {
            # si querés un identificador genérico, podés usar "pk"
            "plu": p.plu,
            "nombre": p.nombre,
            "stock_minimo": p.stock_minimo,
        }
        for p in productos
    ]

    return JsonResponse({"productos": data})


@csrf_exempt
def api_crear_producto(request):
    try:
        data = json.loads(request.body or "{}")
    except:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    nombre = (data.get("nombre") or "").strip()
    plu = (data.get("plu") or "").strip().zfill(3)
    minimo = int(data.get("stock_minimo") or 0)

    if not nombre:
        return JsonResponse({"error": "El nombre es obligatorio"}, status=400)

    if ProductoFijo.objects.filter(plu=plu).exists():
        return JsonResponse({"error": f"Ya existe un producto con PLU {plu}"}, status=400)

    ProductoFijo.objects.create(nombre=nombre, plu=plu, stock_minimo=minimo)

    return JsonResponse({"success": True, "message": "Producto creado correctamente"})


@csrf_exempt
def api_eliminar_producto(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "JSON inválido"}, status=400)

    plu = (data.get("plu") or "").strip()
    if not plu:
        return JsonResponse({"success": False, "error": "Falta 'plu' del producto"}, status=400)

    try:
        p = ProductoFijo.objects.get(plu=plu)
    except ProductoFijo.DoesNotExist:
        return JsonResponse({"success": False, "error": f"Producto con PLU {plu} no encontrado"}, status=404)

    # (Opcional) Evitar borrar si tiene stock/movimientos asociados
    tiene_stock = StockBalde.objects.filter(producto=p).exists()
    tiene_movs = RegistroMovimiento.objects.filter(producto=p).exists()
    if tiene_stock or tiene_movs:
        return JsonResponse({
            "success": False,
            "error": "No se puede eliminar el producto porque tiene stock o movimientos asociados."
        }, status=400)

    p.delete()
    return JsonResponse({"success": True, "message": f"Producto {p.nombre} (PLU {plu}) eliminado correctamente."})


@csrf_exempt
def api_actualizar_producto(request):
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Método no permitido"},
            status=405
        )

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "JSON inválido"},
            status=400
        )

    plu = (data.get("plu") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    stock_minimo = data.get("stock_minimo")

    if not plu:
        return JsonResponse(
            {"success": False, "error": "Falta PLU del producto"},
            status=400
        )

    try:
        p = ProductoFijo.objects.get(plu=plu)
    except ProductoFijo.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": f"No existe producto con PLU {plu}"},
            status=404
        )

    # Actualizar nombre (si vino)
    if nombre:
        p.nombre = nombre

    # Actualizar stock_minimo (si vino)
    if stock_minimo not in (None, ""):
        try:
            p.stock_minimo = int(stock_minimo)
        except ValueError:
            return JsonResponse(
                {"success": False, "error": "stock_minimo debe ser numérico"},
                status=400
            )

    p.save()

    return JsonResponse(
        {"success": True, "message": "Producto actualizado correctamente"},
        status=200
    )

# ---  FIN API CRUD PRODUCTOS

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

@csrf_exempt
def imprimir_stock_total(request):
    """
    Endpoint para imprimir el stock total en la impresora de tickets.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    try:
        print_stock_total()
        return JsonResponse({"ok": True, "message": "Impresión de stock enviada a la impresora."})
    except Exception as e:
        # si querés loggear:
        # logger.exception("Error imprimiendo stock total")
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


def exportar_productos_excel(request):
    """
    Exporta un Excel con las columnas:
    - Nombre
    - PLU

    Lo podés usar como plantilla: agregás nuevas filas y luego
    lo volvés a subir por /cargar_excel/ para alta masiva.
    """
    productos = ProductoFijo.objects.all().order_by("plu")

    filas = [
        {"Nombre": p.nombre, "PLU": p.plu}
        for p in productos
    ]

    # Si no hay productos aún, devolvemos solo el header
    if filas:
        df = pd.DataFrame(filas)
    else:
        df = pd.DataFrame(columns=["Nombre", "PLU"])

    # Escribir a un buffer en memoria
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Productos")

    buffer.seek(0)

    filename = f"productos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    response = HttpResponse(
        buffer,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response



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


# importa tus modelos:
# from .models import RegistroMovimiento, GrupoMovimiento, StockBalde, ProductoFijo

def historial_movimientos(request):
    """
    Lista de movimientos agrupados por grupo_id mostrando SOLO el último
    movimiento de cada grupo, con filtros por fecha, local, tipo.
    NUEVO: si viene ?solo_activos=1, lista baldes activos (con filtros por gusto/código).
    """
    # -------- NUEVO: flag de "solo activos" --------
    solo_activos = request.GET.get("solo_activos") in {"1", "true", "True"}

    # Filtros comunes
    desde_str = request.GET.get("desde")
    hasta_str = request.GET.get("hasta")
    local = (request.GET.get("local") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip().lower()
    gusto = (request.GET.get("gusto") or "").strip()     # nombre del gusto a buscar
    codigo = (request.GET.get("codigo") or "").strip()   # EAN-13 exacto o substring

    # ---------------------------------------------------------------------
    # MODO "SOLO ACTIVOS": devolvemos baldes activos (no historial de grupos)
    # ---------------------------------------------------------------------
    if solo_activos:
        qs = (
            StockBalde.objects
            .filter(is_activo=True)
            .select_related("producto")
            .only("id", "codigo_barras", "peso", "producto__nombre", "producto__plu", "timestamp")
        )

        if gusto:
            qs = qs.filter(producto__nombre__icontains=gusto)
        if codigo:
            qs = qs.filter(codigo_barras__icontains=codigo)

        # Orden: por producto y antigüedad (más viejo primero o después como prefieras)
        qs = qs.order_by("producto__nombre", "timestamp", "id")

        # Totales globales (sobre la búsqueda actual de activos)
        total_kg_global = qs.aggregate(s=Sum("peso"))["s"] or 0

        # Paginación
        page_number = request.GET.get("page", 1)
        paginator = Paginator(qs, 20)
        activos_page = paginator.get_page(page_number)

        # Render usando misma plantilla, con modo=activos
        return render(
            request,
            "historial_movimientos.html",
            {
                "modo": "activos",
                "movimientos": activos_page,  # ahora son StockBalde
                "filtros": {
                    "desde": desde_str or "",
                    "hasta": hasta_str or "",
                    "local": local,
                    "tipo": tipo or "",
                    "gusto": gusto or "",
                    "codigo": codigo or "",
                    "solo_activos": True,
                },
                "total_kg_global": total_kg_global,
            },
        )

    # ---------------------------------------------------------------------
    # MODO HISTORIAL (comportamiento actual)
    # ---------------------------------------------------------------------
    base_qs = RegistroMovimiento.objects.all()

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
            base_qs = base_qs.filter(tipo__in=["retiro", "salida"])
        elif tipo == "ingreso":
            base_qs = base_qs.filter(tipo="ingreso")
        else:
            pass

    if gusto:
        base_qs = base_qs.filter(producto__nombre__icontains=gusto)
    if codigo:
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

    total_kg_global = base_qs.aggregate(s=Sum("peso"))["s"] or 0

    # Paginación
    page_number = request.GET.get("page", 1)
    paginator = Paginator(movimientos_qs, 20)
    movimientos_page = paginator.get_page(page_number)

    # Totales de los grupos visibles (tu lógica actual)
    grupo_ids_visibles = [m.grupo_id for m in movimientos_page.object_list]

    total_kg = (
        GrupoMovimiento.objects
        .filter(grupo_id__in=grupo_ids_visibles)
        .aggregate(s=Sum("total_peso"))["s"] or 0
    )
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
            "modo": "historial",
            "movimientos": movimientos_page,
            "filtros": {
                "desde": desde_str or "",
                "hasta": hasta_str or "",
                "local": local,
                "tipo": tipo or "",
                "gusto": gusto or "",
                "codigo": codigo or "",
                "solo_activos": False,
            },
            "total_kg_global": total_kg_global,
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

    Mejoras anti-duplicados:
    - nuevo_grupo_id se calcula dentro de transaction y serializado
    - opcional: client_txn_id (idempotencia) guardado en sesión
    - chequeo de duplicado con select_for_update para evitar carreras
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
    force = bool(data.get("force", False))

    # ✅ Token opcional para hacer la operación idempotente (recomendado)
    # En el front mandás un UUID por cada confirmación (una sola vez).
    client_txn_id = (data.get("client_txn_id") or "").strip()

    if not productos:
        return JsonResponse({"error": "No hay productos para ingresar"}, status=400)
    if not origen:
        return JsonResponse({"error": "Debe indicar un origen"}, status=400)

    # ---- Idempotencia por sesión (opcional) ----
    # Evita que si el usuario confirma 2 veces, la segunda repita todo.
    if client_txn_id:
        processed = request.session.get("processed_txn_ids", [])
        if client_txn_id in processed:
            # Ya procesado: devolvemos OK sin volver a ingresar.
            return JsonResponse({
                "success": True,
                "status": "ya_procesado",
                "message": "Esta confirmación ya fue procesada.",
            }, status=200)

    ingresados = []

    try:
        with transaction.atomic():
            # ✅ Serializar la generación del grupo_id para evitar carreras
            # Bloquea la fila más “alta” de grupo_id momentáneamente.
            ultimo = (
                RegistroMovimiento.objects
                .select_for_update()
                .order_by("-grupo_id")
                .values_list("grupo_id", flat=True)
                .first()
            )
            ultimo_grupo = ultimo or 0
            nuevo_grupo_id = ultimo_grupo + 1

            for p in productos:
                plu = (p or {}).get("plu")
                peso = (p or {}).get("peso")
                codigo_barras = (p or {}).get("codigo_barras") or (p or {}).get("codigo")

                # Validaciones
                if not plu:
                    return JsonResponse({"error": "Producto sin PLU"}, status=400)
                if peso in (None, "", 0):
                    return JsonResponse({"error": f"Producto {plu} sin peso"}, status=400)

                codigo_str = str(codigo_barras or "")
                if len(codigo_str) != 13 or not codigo_str.isdigit():
                    return JsonResponse(
                        {"error": "Cada balde debe incluir 'codigo_barras' de 13 dígitos"},
                        status=400
                    )

                # Producto
                try:
                    producto_obj = ProductoFijo.objects.get(plu=plu)
                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

                # ✅ Anti-carrera: bloqueamos cualquier balde existente con ese código
                # Si otro request está tratando el mismo código, uno va a esperar al otro.
                duplicado_qs = (
                    StockBalde.objects
                    .select_for_update()
                    .filter(codigo_barras=codigo_str, is_activo=True)
                )

                if duplicado_qs.exists() and not force:
                    ultimo_dup = (
                        duplicado_qs.order_by("-id")
                        .values("producto__nombre", "peso", "fecha_retiro", "timestamp")
                        .first()
                    )
                    return JsonResponse(
                        {
                            "status": "duplicado_detectado",
                            "codigo_barras": codigo_str,
                            "producto": ultimo_dup.get("producto__nombre") if ultimo_dup else None,
                            "peso_anterior": ultimo_dup.get("peso") if ultimo_dup else None,
                            "fecha_retiro": ultimo_dup.get("fecha_retiro") if ultimo_dup else None,
                            "fecha_ingreso": ultimo_dup.get("timestamp").isoformat()
                                if ultimo_dup and ultimo_dup.get("timestamp") else None,
                            "mensaje": f"⚠️ Este balde con código <b>{codigo_str}</b> "
                                       f"ya se encuentra <b>ACTIVO</b> en el stock.<br><br>",
                            "se_puede_forzar": True
                        },
                        status=409
                    )

                # ✅ Crear balde activo
                balde = StockBalde.objects.create(
                    producto=producto_obj,
                    peso=float(peso),
                    codigo_barras=codigo_str,
                    is_activo=True,
                    fecha_retiro=None,
                )

                # ✅ Registrar movimiento
                RegistroMovimiento.objects.create(
                    grupo_id=nuevo_grupo_id,
                    producto=producto_obj,
                    peso=float(peso),
                    tipo="ingreso",
                    origen=origen,
                    boca_salida=origen,  # compatibilidad con layouts existentes
                    codigo_barras=codigo_str,
                )

                ingresados.append(producto_obj.nombre)

            # ✅ Totales del grupo
            _actualizar_total_grupo(nuevo_grupo_id, tipo="ingreso", origen=origen)

            # ✅ Limpiar sesión temporal
            if "productos_temporales" in request.session:
                request.session["productos_temporales"] = []
                request.session.modified = True

            # ✅ Marcar txn_id como procesado (idempotencia)
            if client_txn_id:
                processed = request.session.get("processed_txn_ids", [])
                processed.append(client_txn_id)
                # evito crecimiento infinito
                request.session["processed_txn_ids"] = processed[-50:]
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
    Confirma RETIRO de baldes.

    Escenario actual:
      - TODOS los baldes tienen código de barras.
      - Para cada ítem se espera: {plu, codigo_barras}
      - No hay baldes "legacy" sin código.
      - Si el mismo (plu, codigo_barras) viene repetido en el payload,
        sólo se procesa UNA vez (deduplicación en backend).
      - Si no existe un balde ACTIVO con ese código, se informa como faltante.
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

    if not productos:
        return JsonResponse({"error": "No hay productos para retirar"}, status=400)
    if not destino_nombre:
        return JsonResponse({"error": "Debe indicar un destino"}, status=400)

    # -------- Destino (FK) --------
    destino_obj = BocaSalida.objects.filter(nombre=destino_nombre).first()
    if not destino_obj:
        return JsonResponse({"error": f"Destino '{destino_nombre}' no existe"}, status=400)

    # -------- Normalizar solicitudes y EVITAR DUPLICADOS --------
    # Generamos una lista de (plu, codigo) única
    solicitudes = []
    vistos = set()   # set de (plu, codigo_barras)

    for p in productos:
        p = p or {}
        plu = p.get("plu")
        codigo = (p.get("codigo_barras") or p.get("codigo") or "").strip()

        if not plu:
            return JsonResponse({"error": "Producto sin PLU"}, status=400)
        if not codigo:
            return JsonResponse({"error": f"Producto {plu} sin código de barras"}, status=400)
        if len(codigo) != 13 or not codigo.isdigit():
            return JsonResponse({"error": f"Código inválido para PLU {plu}: debe ser EAN-13"}, status=400)

        clave = (plu, codigo)
        if clave in vistos:
            # Ya tenemos este mismo balde en la lista, lo ignoramos
            continue
        vistos.add(clave)
        solicitudes.append((plu, codigo))

    # -------- Selección de baldes (siempre con código) --------
    seleccionados = []  # [(producto_obj, balde), ...]
    faltantes = []

    for plu, codigo in solicitudes:
        try:
            producto_obj = ProductoFijo.objects.get(plu=plu)
        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

        # Buscamos SIEMPRE por código y sólo baldes activos
        # Si hubiera más de uno con el mismo código, tomamos el MÁS VIEJO
        balde = (
            StockBalde.objects
            .filter(producto=producto_obj, is_activo=True, codigo_barras=codigo)
            .order_by("timestamp", "id")
            .first()
        )

        if not balde:
            faltantes.append(f"{producto_obj.nombre} ({codigo})")
        else:
            seleccionados.append((producto_obj, balde))

    if faltantes:
        return JsonResponse(
            {"error": f"No hay stock disponible para: {', '.join(faltantes)}"},
            status=400
        )

    # -------- Nuevo grupo_id --------
    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    # -------- Ejecutar retiro --------
    productos_retirados = []
    try:
        with transaction.atomic():
            for producto_obj, balde in seleccionados:
                # Marcar balde como inactivo
                balde.is_activo = False
                # (Opcional: si tenés campo fecha_retiro, podés setearlo acá)
                # balde.fecha_retiro = timezone.now()
                balde.save(update_fields=["is_activo"])

                # Registrar movimiento
                RegistroMovimiento.objects.create(
                    grupo_id=nuevo_grupo_id,
                    producto=producto_obj,
                    peso=balde.peso,
                    tipo="salida",
                    destino=destino_obj,
                    boca_salida=destino_nombre,
                    codigo_barras=(balde.codigo_barras or ""),
                )
                productos_retirados.append(producto_obj.nombre)

            # Totales del grupo
            _actualizar_total_grupo(
                nuevo_grupo_id,
                tipo="salida",
                destino_nombre=destino_nombre,
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
            "message": msg,
        },
        status=200,
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

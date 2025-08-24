# views.py (Definición de Vistas)
import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.core.files.storage import FileSystemStorage
from .models import BocaSalida, OrigenIngreso, ProductoFijo, RegistroMovimiento, StockBalde
from django.db.models import Max
import pandas as pd
import sqlite3
from django.db.models import Count
from django.core.paginator import Paginator
from django.views.decorators.cache import cache_page
from django.http import FileResponse
from django.conf import settings
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.db.models import Sum, Count
from app_inventario.models import RegistroMovimiento, GrupoMovimiento, BocaSalida
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Max, Count
import json
from django.shortcuts import render
from django.http import JsonResponse, Http404
from django.db.models import Sum, Count, Max
from .models import RegistroMovimiento, GrupoMovimiento, BocaSalida


def conectar_bd():
    """Conectar a la base de datos SQLite."""
    conn = sqlite3.connect("inventario.db")
    conn.row_factory = sqlite3.Row  # Permite acceder a las columnas por nombre
    return conn


from django.db.models import Count

def index(request):
    stock_resumido = ProductoFijo.objects.annotate(
        cantidad=Count('stockbalde')
    )
    return render(request, "index.html", {"stock_resumido": stock_resumido})



def cargar_productos_desde_excel():
    """
    Carga los productos desde un archivo Excel y los inserta en la base de datos.
    """
    archivo_excel = os.path.join(os.path.dirname(__file__), "productos.xlsx")

    try:
        df = pd.read_excel(archivo_excel)

        # Asegurar que el archivo tiene las columnas necesarias
        if 'Nombre' not in df.columns or 'PLU' not in df.columns:
            return {"error": "El archivo Excel no tiene las columnas necesarias"}

        for _, row in df.iterrows():
            nombre = row['Nombre']
            plu = str(row['PLU']).zfill(3)  # Asegura que el PLU tenga 3 dígitos

            # Agregar producto si no existe
            ProductoFijo.objects.get_or_create(plu=plu, nombre=nombre)

        return {"message": "Productos cargados exitosamente"}

    except Exception as e:
        return {"error": f"Error procesando el archivo: {str(e)}"}


@csrf_exempt
def cargar_productos_excel(request):
    if request.method == "POST" and request.FILES.get("archivo"):
        archivo = request.FILES["archivo"]
        fs = FileSystemStorage(location="uploads/")  # Carpeta donde se guardan los archivos
        nombre_archivo = fs.save(archivo.name, archivo)
        ruta_archivo = fs.path(nombre_archivo)

        try:
            df = pd.read_excel(ruta_archivo)

            # Verificar que tiene las columnas necesarias
            if "Nombre" not in df.columns or "PLU" not in df.columns:
                return JsonResponse({"error": "El archivo debe contener las columnas 'Nombre' y 'PLU'"}, status=400)

            for _, row in df.iterrows():
                nombre = row["Nombre"]
                plu = str(row["PLU"]).zfill(3)  # Asegura que el PLU tenga 3 dígitos

                # Crear el producto si no existe
                ProductoFijo.objects.get_or_create(plu=plu, nombre=nombre)

            return JsonResponse({"message": "Productos cargados correctamente"})

        except Exception as e:
            return JsonResponse({"error": f"Error al procesar el archivo: {str(e)}"}, status=500)

    return JsonResponse({"error": "No se envió ningún archivo"}, status=400)


# Vista para ejecutar la carga manualmente desde la web
def importar_productos(request):
    resultado = cargar_productos_desde_excel()
    return JsonResponse(resultado)

@cache_page(5)  # Cachear por 5 segundos
def obtener_stock(request):
    try:
        # Obtener el stock de cada producto contando los baldes disponibles
        productos_stock = ProductoFijo.objects.all().annotate(
            cantidad=Count("stockbalde")
        ).values("nombre", "cantidad", "stock_minimo")

        # Convertir el queryset a una lista de diccionarios
        stock_list = list(productos_stock)

        return JsonResponse({"stock": stock_list})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def stock_detallado(request):
    stock = StockBalde.objects.select_related("producto").all()
    return render(request, "stock_detallado.html", {"stock_detallado": stock})



def historial(request):
    movimientos_list = RegistroMovimiento.objects.all().order_by('-timestamp')
    paginator = Paginator(movimientos_list, 10)
    page_number = request.GET.get("page", 1)

    try:
        movimientos = paginator.get_page(page_number)
    except:
        return JsonResponse({"error": "Página inválida"}, status=400)

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




# views.py
from django.db.models import Q, Max, OuterRef, Subquery
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
def historial_movimientos(request):
    """
    Lista de movimientos agrupados por grupo_id mostrando SOLO el último
    movimiento de cada grupo, con filtros por fecha, local y tipo.
    """
    base_qs = RegistroMovimiento.objects.all()

    # --- Filtros ---
    desde_str = request.GET.get("desde")
    hasta_str = request.GET.get("hasta")
    local = (request.GET.get("local") or "").strip()
    tipo = request.GET.get("tipo")

    # Fecha (inclusiva por día)
    if desde_str:
        d = parse_date(desde_str)
        if d:
            base_qs = base_qs.filter(timestamp__date__gte=d)
    if hasta_str:
        h = parse_date(hasta_str)
        if h:
            base_qs = base_qs.filter(timestamp__date__lte=h)

    # Local (CharFields + FK destino.nombre)
    if local:
        base_qs = base_qs.filter(
            Q(boca_salida__icontains=local) |   # legado que mostrabas en el template
            Q(origen__icontains=local)       |  # para ingresos
            Q(destino__nombre__icontains=local) # FK -> BocaSalida.nombre
        )

    # Tipo
    if tipo in ("ingreso", "retiro"):
        base_qs = base_qs.filter(tipo=tipo)

    # --- Último movimiento por grupo_id (respetando filtros) ---
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
        .select_related("producto", "destino")  # destino es FK -> BocaSalida
        .order_by("-timestamp", "-id")
    )

    # --- Paginación ---
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
            'origen': origen if tipo=='ingreso' else None,
            'destino': destino_obj if tipo=='salida' else None,
            'total_peso': total,
            'cantidad_items': cant,
        }
    )




def detalle_movimiento(request, grupo_id: int):
    # Items del grupo (los baldes)
    items = (RegistroMovimiento.objects
             .filter(grupo_id=grupo_id)
             .select_related("producto", "destino")
             .order_by("timestamp", "id"))

    if not items.exists():
        raise Http404("Movimiento no encontrado")

    # Header persistido (si lo tienes)
    header = GrupoMovimiento.objects.filter(grupo_id=grupo_id).select_related("destino").first()
    if header:
        total_peso = header.total_peso or 0
        cantidad_items = header.cantidad_items or items.count()
        tipo = header.tipo
        origen = header.origen
        destino = header.destino  # FK a BocaSalida o None
    else:
        # Fallback: calcular al vuelo (si aún no migraste/actualizaste)
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

    # Soporte HTML o JSON (útil para modal por AJAX)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "grupo_id": grupo_id,
            "tipo": tipo,
            "origen": origen,
            "destino": destino.nombre if destino else None,
            "total_peso": round(float(total_peso), 2),
            "cantidad_items": int(cantidad_items),
            "items": [
                {"producto": i.producto.nombre, "peso": float(i.peso)}
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


@csrf_exempt  # Se usa para pruebas, en producción mejor manejar CSRF correctamente
def eliminar_movimiento(request, grupo_id):
    if request.method == "DELETE":
        movimientos = RegistroMovimiento.objects.filter(grupo_id=grupo_id)
        if movimientos.exists():
            movimientos.delete()
            return JsonResponse({"success": True, "message": "Movimiento eliminado correctamente."})
        return JsonResponse({"success": False, "error": "Movimiento no encontrado."}, status=404)

    return JsonResponse({"success": False, "error": "Método no permitido."}, status=405)


def buscar(request):
    return render(request, "index.html")  # Ajusta según lo que necesites

def buscar_detallado(request):
    if request.method == "POST":
        termino_busqueda = request.POST.get("termino_busqueda", "").strip()
        fecha = request.POST.get("fecha", "").strip()

        # Si el usuario no ingresó nada, devolver todos los productos
        if not termino_busqueda and not fecha:
            productos = StockBalde.objects.all()
        else:
            # Buscar por nombre o PLU
            productos = StockBalde.objects.filter(
                producto__nombre__icontains=termino_busqueda
            ) | StockBalde.objects.filter(
                producto__plu__icontains=termino_busqueda
            )

            # Si el usuario ingresó una fecha, filtramos también por fecha
            fecha_formateada = parse_date(fecha)
            if fecha_formateada:
                productos = productos.filter(timestamp__date=fecha_formateada)

        return render(request, "stock_detallado.html", {"stock_detallado": productos})

    return JsonResponse({"error": "Método no permitido"}, status=405)

@csrf_exempt  # Deshabilita protección CSRF para pruebas (evitar en producción)
def reiniciar_lista(request):
    if request.method == "POST":
        global productos_temporales  # Si usas una lista global para los productos escaneados
        productos_temporales = []  # Vacía la lista de productos escaneados
        return JsonResponse({"message": "Lista reiniciada correctamente"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)





def api_stock_detallado(request):
    productos = ProductoFijo.objects.annotate(stock_actual=Count('stockbalde'))
    data = [{"nombre": p.nombre, "stock_minimo": p.stock_minimo, "cantidad": p.stock_actual} for p in productos]
    return JsonResponse({"stock_detallado": data})



productos_temporales = []  # Lista temporal de productos escaneados

from django.http import JsonResponse

productos_temporales = []  # Lista temporal de productos escaneados

@csrf_exempt
def obtener_codigos(request):
    global productos_temporales
    return JsonResponse({"productos": productos_temporales}, safe=False)



# Modificar la lógica de escaneo para que los productos no se agreguen directamente a la tabla
productos_temporales = []  # Lista temporal de productos escaneados

@csrf_exempt
def procesar_codigo(request):
    global productos_temporales  # Asegurar que la variable es global
    
    if request.method == 'POST':
        data = json.loads(request.body)
        codigo_barras = data.get("codigo")

        if not codigo_barras or len(codigo_barras) != 13:
            return JsonResponse({"error": "Código de barras no válido"}, status=400)

        plu = codigo_barras[2:5]
        peso = float(f"{codigo_barras[8]}.{codigo_barras[9:12]}")

        try:
            producto = ProductoFijo.objects.get(plu=plu)
            nuevo_producto = {
                "nombre": producto.nombre,
                "peso": peso,
                "plu": plu
            }

            print("📌 Producto escaneado:", nuevo_producto)

            # Obtener la lista temporal desde la sesión (importante para mantener estado)
            productos_temporales = request.session.get("productos_temporales", [])

            if not any(p["plu"] == nuevo_producto["plu"] and p["peso"] == nuevo_producto["peso"] for p in productos_temporales):
                productos_temporales.append(nuevo_producto)

            request.session["productos_temporales"] = productos_temporales
            request.session.modified = True

            print("📌 Lista de productos actualizada:", productos_temporales)

            return JsonResponse({
                "message": "Producto agregado temporalmente",
                "productos_temporales": productos_temporales
            })

        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=400)






@csrf_exempt
def obtener_productos_temporales(request):
    productos_temporales = request.session.get("productos_temporales", [])
    print("📌 Productos Temporales Actuales:", productos_temporales)
    return JsonResponse({"productos": productos_temporales})




@csrf_exempt
def confirmar_agregado(request):
    """Guarda en la base de datos los productos escaneados solo cuando se presiona 'Aceptar' en el modal."""
    global productos_temporales

    if request.method == 'POST':
        if not productos_temporales:
            return JsonResponse({"error": "No hay productos para confirmar"}, status=400)

        productos_agregados = []

        for producto in productos_temporales:
            try:
                producto_obj = ProductoFijo.objects.get(plu=producto["plu"])
                StockBalde.objects.create(producto=producto_obj, peso=producto["peso"])
                productos_agregados.append(producto_obj.nombre)
            except ProductoFijo.DoesNotExist:
                return JsonResponse({"error": f"Producto con PLU {producto['plu']} no encontrado"}, status=404)

        productos_temporales = []  # Vaciar lista temporal tras confirmación

        return JsonResponse({"message": f"Productos agregados correctamente: {', '.join(productos_agregados)} ✅"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)

@csrf_exempt
def reiniciar_lista_temporal(request):
    """Vacía la lista temporal de productos escaneados en la sesión del usuario."""
    request.session["productos_temporales"] = []
    request.session.modified = True
    return JsonResponse({"message": "Lista de productos escaneados reiniciada"})


from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Max
import json

@csrf_exempt
def confirmar_codigos(request):
    """
    Confirma INGRESO de productos (baldes), agrupando todo en un nuevo grupo_id.
    - Valida payload.
    - Usa transacción para coherencia.
    - Crea StockBalde por cada balde ingresado.
    - Registra RegistroMovimiento por cada balde (tipo='ingreso') con 'origen'.
    - Actualiza total de peso del grupo en GrupoMovimiento.
    - Limpia productos temporales de la sesión.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # --- Parseo payload ---
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    productos = data.get("productos", [])
    origen = (data.get("origen") or "").strip()

    # Si no vienen en el body, intentamos desde la sesión (flujo actual)
    if not productos:
        productos = request.session.get("productos_temporales", [])

    if not productos:
        return JsonResponse({"error": "No hay productos para ingresar"}, status=400)

    if not origen:
        return JsonResponse({"error": "Debe indicar un origen"}, status=400)

    # --- Determinar nuevo grupo_id ---
    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    # --- Ejecutar ingreso en transacción ---
    nombres_ingresados = []

    try:
        with transaction.atomic():
            for p in productos:
                plu = (p or {}).get("plu")
                nombre = (p or {}).get("nombre")
                peso = (p or {}).get("peso")

                if not plu:
                    return JsonResponse({"error": "Producto sin PLU"}, status=400)
                if not peso:
                    return JsonResponse({"error": f"Producto {nombre or plu} sin peso"}, status=400)

                # Producto catálogo
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
                    origen=origen,            # origen (CharField)
                    boca_salida=origen        # compatibilidad con campo legado si lo usabas para mostrar
                )

                nombres_ingresados.append(producto_obj.nombre)

            # 3) Actualizar totales del grupo (persistente)
            _actualizar_total_grupo(
                nuevo_grupo_id,
                tipo="ingreso",
                origen=origen
            )

            # 4) Limpiar lista temporal de la sesión
            if "productos_temporales" in request.session:
                request.session["productos_temporales"] = []
                request.session.modified = True

    except Exception as e:
        return JsonResponse({"error": f"Error al confirmar ingreso: {e}"}, status=500)

    # Respuesta: mensaje con \n (el front lo puede transformar a <br> o a <ul>)
    msg = "Productos agregados correctamente:\n\n" + "\n".join(nombres_ingresados)
    return JsonResponse(
        {
            "success": True,
            "grupo_id": nuevo_grupo_id,
            "origen": origen,
            "productos": nombres_ingresados,
            "message": msg
        },
        status=200
    )




@csrf_exempt
def eliminar_producto_temporal(request):
    """ Elimina un producto específico de la lista de productos temporales en la sesión. """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            plu = data.get("plu")

            # Obtener la lista actual de la sesión
            productos_temporales = request.session.get("productos_temporales", [])

            # Filtrar para eliminar el producto con el PLU recibido
            productos_temporales = [p for p in productos_temporales if p["plu"] != plu]

            # Guardar la lista actualizada en la sesión
            request.session["productos_temporales"] = productos_temporales
            request.session.modified = True

            return JsonResponse({"success": True, "message": "Producto eliminado de la sesión."})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

def actualizar_stock_minimo(request):
    if request.method == "POST":
        data = json.loads(request.body)
        productos = data.get("productos", [])

        for producto in productos:
            ProductoFijo.objects.filter(nombre=producto["nombre"]).update(stock_minimo=producto["stock_minimo"])

        return JsonResponse({"message": "Stock mínimo actualizado"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)

def agregar_productos(request):
    if request.method == "POST":
        data = json.loads(request.body)
        productos = data.get("productos", [])

        for producto in productos:
            plu = producto.get("plu")
            peso = producto.get("peso")
            producto_obj = ProductoFijo.objects.get(plu=plu)
            StockBalde.objects.create(producto=producto_obj, peso=peso)

        return JsonResponse({"message": "Productos agregados exitosamente"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


@csrf_exempt
def retirar_producto(request):
    if request.method == "POST":
        data = json.loads(request.body)
        plu = data.get("plu")

        if not plu:
            return JsonResponse({"error": "PLU no proporcionado"}, status=400)

        try:
            producto = ProductoFijo.objects.get(plu=plu)
            balde = StockBalde.objects.filter(producto=producto).order_by("-timestamp").first()

            if balde:
                balde.delete()
                RegistroMovimiento.objects.create(grupo_id=1, producto=producto, peso=balde.peso, tipo="retiro")
                return JsonResponse({"message": "Producto retirado correctamente"}, status=200)
            else:
                return JsonResponse({"error": "No hay stock disponible para este producto"}, status=400)

        except ProductoFijo.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

    return JsonResponse({"error": "Método no permitido"}, status=405)


@csrf_exempt
def confirmar_retiro(request):
    """
    Confirma el retiro de productos (baldes), agrupando todo en un nuevo grupo_id.
    - Valida stock antes de modificar.
    - Usa transacción para coherencia.
    - Registra destino (FK) y mantiene boca_salida (texto) para compatibilidad.
    - Actualiza total de peso del grupo.
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

    # --- Lookup de destino (FK) ---
    destino_obj = BocaSalida.objects.filter(nombre=destino_nombre).first()
    if not destino_obj:
        return JsonResponse({"error": f"Destino '{destino_nombre}' no existe"}, status=400)

    # --- Agrupar por PLU para validar stock antes de tocar BD ---
    # contar cuántos baldes quiere retirar por producto
    pedidos_por_plu = {}
    for p in productos:
        plu = (p or {}).get("plu")
        if not plu:
            return JsonResponse({"error": "Producto sin PLU"}, status=400)
        pedidos_por_plu[plu] = pedidos_por_plu.get(plu, 0) + 1

    # Validación de stock: si falta alguno, abortamos antes de borrar
    nombres_sin_stock = []
    productos_resueltos = {}  # plu -> (producto_obj, queryset baldes para retirar)
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
        return JsonResponse(
            {"error": f"No hay stock disponible para: {', '.join(nombres_sin_stock)}"},
            status=400
        )

    # --- Obtener nuevo grupo_id ---
    ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
    nuevo_grupo_id = ultimo_grupo + 1

    # --- Ejecutar retiro en transacción ---
    productos_retirados = []

    try:
        with transaction.atomic():
            for plu, (producto_obj, baldes_qs) in productos_resueltos.items():
                for balde in baldes_qs:
                    peso = balde.peso
                    # eliminar el balde de stock
                    balde.delete()
                    # registrar movimiento
                    RegistroMovimiento.objects.create(
                        grupo_id=nuevo_grupo_id,
                        producto=producto_obj,
                        peso=peso,
                        tipo="salida",
                        destino=destino_obj,             # FK correcto
                        boca_salida=destino_nombre       # compatibilidad con campo texto legado
                    )
                    productos_retirados.append(producto_obj.nombre)

            # actualizar totales del grupo (persistente)
            _actualizar_total_grupo(
                nuevo_grupo_id,
                tipo="salida",
                destino_nombre=destino_nombre
            )

    except Exception as e:
        return JsonResponse({"error": f"Error al retirar productos: {e}"}, status=500)

    # Respuesta: mensaje con saltos \n (el front puede reemplazar por <br>)
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



productos_temporales = []  # Lista temporal de productos escaneados

def interpretar_codigo_barras(codigo_barras):
    """ Extrae el PLU y el peso del código de barras. """
    if len(codigo_barras) == 13 and codigo_barras.isdigit():
        plu = codigo_barras[2:5]  # Los tres siguientes son el PLU
        peso_parte_entera = codigo_barras[8]
        peso_parte_decimal = codigo_barras[9:12]
        peso = f"{peso_parte_entera}.{peso_parte_decimal}"
        return {"plu": plu, "peso": float(peso)}
    return {"error": "Código de barras no válido"}


@csrf_exempt
def actualizar_stock_minimo(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            productos = data.get("productos", [])

            if not productos:
                return JsonResponse({"error": "No se enviaron productos"}, status=400)

            for producto in productos:
                plu = producto.get("plu")
                nuevo_stock = producto.get("stock_minimo")

                if not plu or nuevo_stock is None:
                    return JsonResponse({"error": "Datos incompletos"}, status=400)

                producto_obj = ProductoFijo.objects.filter(plu=plu).first()
                if producto_obj:
                    producto_obj.stock_minimo = int(nuevo_stock)
                    producto_obj.save()

            return JsonResponse({"success": True, "message": "Stock mínimo actualizado correctamente"})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# Bocas de Salida

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
            data = json.loads(request.body)
            nombre = data.get("nombre", "").strip()

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
            data = json.loads(request.body)
            nombre = data.get("nombre", "").strip()

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
            data = json.loads(request.body)
            nombre = data.get("nombre", "").strip()

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
            data = json.loads(request.body)
            nombre = data.get("nombre", "").strip()

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


# Backups  

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


# views.py (Definición de Vistas)
import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.core.files.storage import FileSystemStorage
from .models import ProductoFijo, RegistroMovimiento, StockBalde
from django.db.models import Max
import pandas as pd
import sqlite3
from django.db.models import Count

def conectar_bd():
    """Conectar a la base de datos SQLite."""
    conn = sqlite3.connect("inventario.db")
    conn.row_factory = sqlite3.Row  # Permite acceder a las columnas por nombre
    return conn


def index(request):
    stock_resumido = ProductoFijo.objects.all()
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
    return render(request, "historial.html")


def historial_movimientos(request):
    """
    Obtiene una lista de movimientos únicos agrupados por grupo_id.
    Muestra solo el último movimiento de cada grupo_id para evitar duplicados.
    """
    movimientos = (
        RegistroMovimiento.objects.values("grupo_id")
        .annotate(ultimo_movimiento=Max("timestamp"))
        .order_by("-ultimo_movimiento")
    )

    # Obtener el último registro de cada grupo_id para mostrar en el historial
    movimientos_detalle = RegistroMovimiento.objects.filter(
        grupo_id__in=[mov["grupo_id"] for mov in movimientos]
    ).order_by("-timestamp")

    # Removemos duplicados usando un diccionario
    movimientos_dict = {}
    for mov in movimientos_detalle:
        if mov.grupo_id not in movimientos_dict:
            movimientos_dict[mov.grupo_id] = mov  # Guardamos solo el primer registro de cada grupo_id

    return render(request, "historial_movimientos.html", {"movimientos": movimientos_dict.values()})


def detalle_movimiento(request, grupo_id):
    """
    Devuelve solo los registros del grupo_id específico.
    """
    detalles = RegistroMovimiento.objects.filter(grupo_id=grupo_id).order_by("timestamp")

    data = [
        {
            "producto": detalle.producto.nombre,
            "peso": detalle.peso,
            "tipo": detalle.tipo,
            "fecha": detalle.timestamp.strftime("%d/%m/%Y %H:%M")
        }
        for detalle in detalles
    ]
    
    return JsonResponse(data, safe=False)


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


@csrf_exempt
def confirmar_codigos(request):
    """
    Guarda en la base de datos los productos escaneados solo cuando se presiona 'Aceptar' en el modal,
    e informa qué productos fueron agregados.
    """
    if request.method == "POST":
        try:
            productos_temporales = request.session.get("productos_temporales", [])

            if not productos_temporales:
                return JsonResponse({"error": "No hay productos para confirmar"}, status=400)

            # Obtener el último grupo_id y sumarle 1
            ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
            nuevo_grupo_id = ultimo_grupo + 1

            productos_agregados = []

            for producto in productos_temporales:
                try:
                    producto_obj = ProductoFijo.objects.get(plu=producto["plu"])
                    StockBalde.objects.create(producto=producto_obj, peso=producto["peso"])

                    # Guardar en el historial de movimientos
                    RegistroMovimiento.objects.create(
                        grupo_id=nuevo_grupo_id,
                        producto=producto_obj,
                        peso=producto["peso"],
                        tipo="ingreso"
                    )

                    productos_agregados.append(producto_obj.nombre)

                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {producto['plu']} no encontrado"}, status=404)

            request.session["productos_temporales"] = []  # Vaciar la lista en la sesión
            request.session.modified = True

            return JsonResponse({
                "message": f"Productos agregados correctamente:\n\n {'\n'.join(productos_agregados)}"
            }, status=200)

        except Exception as e:
            return JsonResponse({"error": f"Error al confirmar productos: {str(e)}"}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)


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
    Confirma el retiro de productos, asegurándose de agruparlos en un nuevo grupo_id.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            productos = data.get("productos", [])

            if not productos:
                return JsonResponse({"error": "No hay productos para retirar"}, status=400)

            # Obtener el último grupo_id y sumarle 1
            ultimo_grupo = RegistroMovimiento.objects.aggregate(Max("grupo_id"))["grupo_id__max"] or 0
            nuevo_grupo_id = ultimo_grupo + 1

            productos_sin_stock = []
            productos_retirados = []

            for producto in productos:
                plu = producto.get("plu")
                try:
                    producto_obj = ProductoFijo.objects.get(plu=plu)
                    balde = StockBalde.objects.filter(producto=producto_obj).order_by("-timestamp").first()

                    if not balde:
                        productos_sin_stock.append(producto_obj.nombre)
                        continue  # ❌ No intentar eliminar si no hay stock

                    balde.delete()

                    # Guardar en el historial de movimientos
                    RegistroMovimiento.objects.create(
                        grupo_id=nuevo_grupo_id,
                        producto=producto_obj,
                        peso=balde.peso,
                        tipo="retiro"
                    )
                    productos_retirados.append(producto_obj.nombre)

                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

            if productos_sin_stock:
                return JsonResponse({
                    "error": f"No hay stock disponible para los siguientes productos: {', '.join(productos_sin_stock)}"
                }, status=400)

            return JsonResponse({"message": f"Productos retirados correctamente:\n\n {'\n'.join(productos_retirados)} "}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Formato JSON inválido"}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405)


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
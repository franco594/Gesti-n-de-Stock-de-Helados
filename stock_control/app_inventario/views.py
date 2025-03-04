# views.py (Definición de Vistas)
import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from .models import ProductoFijo, RegistroMovimiento, StockBalde
import pandas as pd
import sqlite3

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


# Vista para ejecutar la carga manualmente desde la web
def importar_productos(request):
    resultado = cargar_productos_desde_excel()
    return JsonResponse(resultado)


def stock_detallado(request):
    stock = StockBalde.objects.select_related("producto").all()
    return render(request, "stock_detallado.html", {"stock_detallado": stock})

def historial(request):
    return render(request, "historial.html")

def obtener_historial_movimientos(request):
    movimientos = RegistroMovimiento.objects.select_related("producto").all().order_by("-timestamp")
    return render(request, "historial.html", {"movimientos": movimientos})


def obtener_detalle_movimiento(request, grupo_id):
    try:
        movimientos = RegistroMovimiento.objects.filter(grupo_id=grupo_id).select_related("producto")

        detalles = [
            {
                "nombre": movimiento.producto.nombre,
                "peso": movimiento.peso,
                "tipo": movimiento.tipo,
                "timestamp": movimiento.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            }
            for movimiento in movimientos
        ]

        return JsonResponse(detalles, safe=False)

    except Exception as e:
        return JsonResponse({"error": f"Error al obtener detalles del movimiento: {str(e)}"}, status=500)



def buscar(request):
    return render(request, "index.html")  # Ajusta según lo que necesites

def buscar_detallado(request):
    if request.method == "POST":
        termino_busqueda = request.POST.get("termino_busqueda", "").strip()
        fecha = request.POST.get("fecha", "")

        # Filtrar productos por nombre o PLU
        productos = StockBalde.objects.filter(producto__nombre__icontains=termino_busqueda)

        if fecha:
            productos = productos.filter(fecha_ingreso=fecha)

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
    productos = ProductoFijo.objects.all()
    data = [{"nombre": p.nombre, "stock_minimo": p.stock_minimo, "cantidad": p.stockbalde_set.count()} for p in productos]
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

        for producto in productos_temporales:
            producto_obj = ProductoFijo.objects.get(plu=producto["plu"])
            StockBalde.objects.create(producto=producto_obj, peso=producto["peso"])

        productos_temporales = []  # Vaciar lista temporal tras confirmación
        return JsonResponse({"message": "Productos agregados exitosamente"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


@csrf_exempt
def reiniciar_lista_temporal(request):
    """Vacía la lista temporal de productos escaneados en la sesión del usuario."""
    request.session["productos_temporales"] = []
    request.session.modified = True
    return JsonResponse({"message": "Lista de productos escaneados reiniciada"})


@csrf_exempt
def confirmar_codigos(request):
    if request.method == "POST":
        try:
            productos_temporales = request.session.get("productos_temporales", [])

            if not productos_temporales:
                return JsonResponse({"error": "No hay productos para confirmar"}, status=400)

            for producto in productos_temporales:
                producto_obj = ProductoFijo.objects.get(plu=producto["plu"])
                StockBalde.objects.create(producto=producto_obj, peso=producto["peso"])

            request.session["productos_temporales"] = []  # Vaciar la lista en la sesión
            request.session.modified = True

            return JsonResponse({"message": "Productos agregados✅"}, status=200)
        
        except Exception as e:
            return JsonResponse({"error": f"Error al confirmar productos: {str(e)}"}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)




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
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            productos = data.get("productos", [])

            if not productos:
                return JsonResponse({"error": "No hay productos para retirar"}, status=400)

            for producto in productos:
                plu = producto.get("plu")
                try:
                    producto_obj = ProductoFijo.objects.get(plu=plu)
                    balde = StockBalde.objects.filter(producto=producto_obj).order_by("-timestamp").first()

                    if balde:
                        balde.delete()
                        RegistroMovimiento.objects.create(grupo_id=1, producto=producto_obj, peso=balde.peso, tipo="retiro")
                    else:
                        return JsonResponse({"error": f"No hay stock disponible para el producto {producto_obj.nombre}"}, status=400)

                except ProductoFijo.DoesNotExist:
                    return JsonResponse({"error": f"Producto con PLU {plu} no encontrado"}, status=404)

            return JsonResponse({"message": "Productos retirados correctamente"}, status=200)

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
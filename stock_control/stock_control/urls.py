
from django.urls import path
from app_inventario.views import (
    api_stock_detallado, buscar_detallado, cargar_productos_excel, detalle_movimiento, historial_movimientos, importar_productos, index, obtener_productos_temporales, procesar_codigo, stock_detallado, historial, buscar,
    agregar_productos, retirar_producto, procesar_codigo,
    obtener_codigos, confirmar_codigos, confirmar_retiro, agregar_productos, actualizar_stock_minimo, reiniciar_lista_temporal,
)

urlpatterns = [
    path('', index, name="index"),
    path('api/importar_productos/', importar_productos, name="importar_productos"),
    path('api/stock_detallado/', api_stock_detallado, name="api_stock_detallado"),
    path('historial/', historial, name="historial"),
    path('buscar/', buscar, name="buscar"),
    path("buscar_detallado/", buscar_detallado, name="buscar_detallado"),  # Agregar la URL
    path("api/obtener_productos_temporales/", obtener_productos_temporales, name="obtener_productos_temporales"),
    path('api/agregar_producto/', agregar_productos, name="agregar_producto"),
    path('api/retirar_producto/', retirar_producto, name="retirar_producto"),
    path('api/procesar_codigo/', procesar_codigo, name="procesar_codigo"),
    path('api/obtener_codigos/', obtener_codigos, name="obtener_codigos"),
    path('api/confirmar_codigos/', confirmar_codigos, name="confirmar_codigos"),
    path('api/confirmar_retiro/', confirmar_retiro, name="confirmar_retiro"),
    path('api/agregar_productos/', agregar_productos, name="agregar_productos"),
    path('api/actualizar_stock_minimo/', actualizar_stock_minimo, name="actualizar_stock_minimo"),
    path("api/reiniciar_lista_temporal/", reiniciar_lista_temporal, name="reiniciar_lista"),
    path('historial_movimientos/', historial_movimientos, name='historial_movimientos'),
    path('detalle_movimiento/<int:grupo_id>/', detalle_movimiento, name='detalle_movimiento'),
    path("cargar_excel/", cargar_productos_excel, name="cargar_excel"),
]


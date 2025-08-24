
from django.urls import path
from app_inventario.views import (
    api_stock_detallado, buscar_detallado, cargar_productos_excel, crear_boca, crear_origen, descargar_backup, detalle_movimiento, eliminar_boca_salida, eliminar_movimiento, eliminar_origen, eliminar_producto_temporal, historial_movimientos, importar_backup, importar_productos, index, obtener_bocas_salida, obtener_origenes, obtener_productos_temporales, obtener_stock, procesar_codigo, historial, buscar,
    agregar_productos, reiniciar_stock, retirar_producto, procesar_codigo,
    obtener_codigos, confirmar_codigos, confirmar_retiro, agregar_productos, actualizar_stock_minimo, reiniciar_lista_temporal, 
)

urlpatterns = [
    path('', index, name="index"),
    path('api/importar_productos/', importar_productos, name="importar_productos"),
    path('api/obtener_stock/', obtener_stock, name='obtener_stock'),
    path('api/stock_detallado/', api_stock_detallado, name="api_stock_detallado"),
    path('historial/', historial, name="historial"),
    path('buscar/', buscar, name="buscar"),
    path("buscar_detallado/", buscar_detallado, name="buscar_detallado"),  # Agregar la URL
    path("api/obtener_productos_temporales/", obtener_productos_temporales, name="obtener_productos_temporales"),
    path("api/eliminar_producto_temporal/", eliminar_producto_temporal, name="eliminar_producto_temporal"),
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
    path('eliminar_movimiento/<int:grupo_id>/', eliminar_movimiento, name='eliminar_movimiento'),
    path("cargar_excel/", cargar_productos_excel, name="cargar_excel"),
    path('api/obtener_bocas_salida/', obtener_bocas_salida, name='obtener_bocas'),
    path('api/crear_boca/', crear_boca, name='crear_boca'),
    path("api/crear_boca_salida/", crear_boca, name="crear_boca_salida"),
    path("api/obtener_origenes/", obtener_origenes, name="obtener_origenes"),
    path("api/crear_origen/", crear_origen, name="crear_origen"),
    path('api/eliminar_boca_salida/', eliminar_boca_salida, name="eliminar_boca_salida"),
    path('api/eliminar_origen/', eliminar_origen, name="eliminar_origen"),
    path('descargar_backup/', descargar_backup, name='descargar_backup'),
    path('importar_backup/', importar_backup, name='importar_backup'),
    path("reiniciar_stock/", reiniciar_stock, name="reiniciar_stock"),
    path("movimientos/<int:grupo_id>/", detalle_movimiento, name="movimientos_detalle_json"),

]


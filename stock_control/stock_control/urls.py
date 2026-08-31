from django.urls import path
from app_inventario.views import (
    # Home / stock
    api_actualizar_producto, api_crear_producto, api_dashboard_metricas, api_eliminar_producto,
    api_listar_productos, api_toggle_plu_activo,
    dashboard, exportar_productos_excel, imprimir_stock_total, index, cargar_productos_excel, importar_productos,
    obtener_stock, api_stock_detallado, stock_detallado,
    actualizar_stock_minimo,

    # Historial / movimientos
    historial, historial_movimientos, detalle_movimiento, eliminar_movimiento, eliminar_item_movimiento,

    # Búsqueda
    buscar, buscar_detallado,

    # Escaneo temporal (sesión)
    procesar_codigo, obtener_codigos, obtener_productos_temporales,
    eliminar_producto_temporal, reiniciar_lista_temporal,

    # Confirmaciones agrupadas
    confirmar_agregado, confirmar_codigos, confirmar_retiro,

    # Catálogos
    obtener_bocas, crear_boca, crear_origen,
    obtener_bocas_salida, obtener_origenes,
    eliminar_boca_salida, eliminar_origen,

    # Backups / mantenimiento
    descargar_backup, importar_backup, reiniciar_stock,

    reimprimir_ticket,

    # Auto-updater
    api_check_update, api_apply_update,

    # Devolución
    confirmar_devolucion,

    # Conciliación
    conciliacion, api_conciliacion_datos, api_conciliacion_guardar, api_conciliacion_exportar,

    # Edición de ítems
    api_editar_item_movimiento,

    # Configuración de precios
    config_precios, api_config_precios,
)

urlpatterns = [
    # Home / stock
    path('', index, name="index"),
    path('api/importar_productos/', importar_productos, name="importar_productos"),
     # 🔹 Productos (admin)
    path("api/productos/", api_listar_productos, name="api_listar_productos"),
    path("api/crear_producto/", api_crear_producto, name="api_crear_producto"),
    path("api/actualizar_producto/", api_actualizar_producto, name="api_actualizar_producto"),  # 👈 NUEVA
    path("api/eliminar_producto/", api_eliminar_producto, name="api_eliminar_producto"),
    path("api/toggle_plu_activo/", api_toggle_plu_activo, name="api_toggle_plu_activo"),
    path('api/obtener_stock/', obtener_stock, name='obtener_stock'),
    path('api/stock_detallado/', api_stock_detallado, name="api_stock_detallado"),
    path('stock/detallado/', stock_detallado, name="stock_detallado"),
    path('cargar_excel/', cargar_productos_excel, name="cargar_excel"),
    path("exportar_productos_excel/", exportar_productos_excel, name="exportar_productos_excel"),
    path("api/actualizar_stock_minimo/", actualizar_stock_minimo, name="actualizar_stock_minimo"),
    path('api/print_stock_total/', imprimir_stock_total, name="imprimir_stock_total"),

    # Historial / movimientos agrupados
    path('historial/', historial, name="historial"),
    path('historial_movimientos/', historial_movimientos, name='historial_movimientos'),
    path('detalle_movimiento/<int:grupo_id>/', detalle_movimiento, name='detalle_movimiento'),
    # Alias opcional (por compatibilidad con el front)
    path('movimientos/<int:grupo_id>/', detalle_movimiento, name='movimientos_detalle_json'),
    path('eliminar_movimiento/<int:grupo_id>/', eliminar_movimiento, name='eliminar_movimiento'),
    path('api/eliminar_item_movimiento/', eliminar_item_movimiento, name='eliminar_item_movimiento'),
    path('api/movimientos/<int:grupo_id>/reimprimir/', reimprimir_ticket, name='reimprimir_ticket'),

    # Búsqueda
    path('buscar/', buscar, name="buscar"),
    path('buscar_detallado/', buscar_detallado, name="buscar_detallado"),

    # Escaneo temporal (sesión)
    path('api/procesar_codigo/', procesar_codigo, name="procesar_codigo"),
    path('api/obtener_codigos/', obtener_codigos, name="obtener_codigos"),
    path('api/obtener_productos_temporales/', obtener_productos_temporales, name="obtener_productos_temporales"),
    path('api/eliminar_producto_temporal/', eliminar_producto_temporal, name="eliminar_producto_temporal"),
    path('api/reiniciar_lista_temporal/', reiniciar_lista_temporal, name="reiniciar_lista_temporal"),

    # Confirmaciones agrupadas
    path('api/confirmar_codigos/', confirmar_codigos, name="confirmar_codigos"),  # ingreso (grupo)
    path('api/confirmar_retiro/', confirmar_retiro, name="confirmar_retiro"),     # retiro (grupo)
    path('api/confirmar_agregado/', confirmar_agregado, name="confirmar_agregado"),  # legacy opcional

    # Catálogos
    path('api/bocas/', obtener_bocas, name='obtener_bocas'),
    path('api/obtener_bocas_salida/', obtener_bocas_salida, name='obtener_bocas_salida'),
    path('api/obtener_origenes/', obtener_origenes, name="obtener_origenes"),
    path('api/crear_boca/', crear_boca, name='crear_boca'),
    path('api/crear_boca_salida/', crear_boca, name="crear_boca_salida"),  # alias al mismo handler
    path('api/crear_origen/', crear_origen, name="crear_origen"),
    path('api/eliminar_boca_salida/', eliminar_boca_salida, name="eliminar_boca_salida"),
    path('api/eliminar_origen/', eliminar_origen, name="eliminar_origen"),


    # Backups / mantenimiento
    path('descargar_backup/', descargar_backup, name='descargar_backup'),
    path('importar_backup/', importar_backup, name='importar_backup'),
    path('reiniciar_stock/', reiniciar_stock, name="reiniciar_stock"),

    # Dashboard
    path('dashboard/', dashboard, name='dashboard'),
    path('api/dashboard/metricas/', api_dashboard_metricas, name='api_dashboard_metricas'),

    # Auto-updater
    path('api/check-update/', api_check_update, name='api_check_update'),
    path('api/apply-update/', api_apply_update, name='api_apply_update'),

    # Devolución
    path('api/confirmar_devolucion/', confirmar_devolucion, name='confirmar_devolucion'),

    # Conciliación
    path('conciliacion/', conciliacion, name='conciliacion'),
    path('api/conciliacion/', api_conciliacion_datos, name='api_conciliacion_datos'),
    path('api/conciliacion/guardar/', api_conciliacion_guardar, name='api_conciliacion_guardar'),
    path('api/conciliacion/exportar/', api_conciliacion_exportar, name='api_conciliacion_exportar'),

    # Edición de ítem individual
    path('api/editar_item_movimiento/', api_editar_item_movimiento, name='api_editar_item_movimiento'),

    # Configuración de precios
    path('config/precios/', config_precios, name='config_precios'),
    path('api/config/precios/', api_config_precios, name='api_config_precios'),
]

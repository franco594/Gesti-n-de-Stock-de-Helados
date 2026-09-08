# Sistema de stock de baldes

Aplicación Django con SQLite, JavaScript y ejecutable PyInstaller para Windows.

## Reglas fundamentales

- Nunca modificar directamente db.sqlite3, seed_db.sqlite3 ni backups.
- Nunca ejecutar reiniciar_stock durante pruebas.
- Toda migración de datos debe tener modo --dry-run y generar un informe.
- Nunca corregir movimientos históricos automáticamente al iniciar la app.
- Stock actual significa solamente StockBalde con is_activo=True.
- codigo_barras no identifica necesariamente un balde físico único.
- Dos baldes del mismo PLU y peso pueden tener el mismo código.
- Cada balde físico debe distinguirse por su ID interno.
- Los retiros, ingresos y devoluciones deben ser atómicos e idempotentes.
- No deduplicar baldes solamente por codigo_barras.
- Antes de modificar código, explicar el problema y proponer un plan.
- Cada corrección debe incluir una prueba que reproduzca el error.
- Ejecutar todas las pruebas antes de declarar terminada una tarea.
- No realizar cambios de seguridad, actualización o base de datos fuera del alcance solicitado.

## Diseño y experiencia de usuario

La aplicación debe parecer un programa profesional de escritorio,
no una página web ni una landing comercial.

Referencia visual: aplicaciones como AnyDesk.

Objetivos:

- Interfaz compacta, limpia y consistente.
- Navegación sencilla y siempre visible.
- Priorizar rapidez de operación y prevención de errores.
- Usar Work Sans, ya almacenada localmente.
- Evitar emojis como iconos de interfaz.
- Utilizar iconos consistentes y discretos.
- Verde solamente para éxito o stock correcto.
- Rojo solamente para peligro, eliminación o falta de stock.
- Todos los botones deben tener estados normal, hover, disabled y loading.
- Las tablas deben tener encabezado fijo y buena legibilidad.
- Mostrar claramente estados de carga, error, vacío y operación completada.
- No modificar modelos, base de datos ni lógica de stock durante tareas visuales.
- Evitar CSS inline.
- Reutilizar componentes y variables CSS.
- Mantener compatibilidad con pantallas de 1366×768 y 1920×1080.
- No utilizar dependencias externas ni CDN.

## Flujo de trabajo

1. Investigar sin modificar.
2. Reproducir el error con una prueba.
3. Implementar el cambio mínimo.
4. Ejecutar pruebas.
5. Revisar git diff.
6. Informar riesgos y archivos modificados.

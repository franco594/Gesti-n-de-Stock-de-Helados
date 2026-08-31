# models.py - OPTIMIZADO CON ÍNDICES COMPLETOS
from django.db import models

class ProductoFijo(models.Model):
    plu = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=255, db_index=True)
    stock_minimo = models.IntegerField(default=5)
    # True = PLU en uso (aparece en impresión de stock aunque tenga 0 baldes)
    # False = PLU inactivo (sabor discontinuado, no aparece en reportes de impresión)
    is_activo = models.BooleanField(default=True, db_index=True, verbose_name='Activo')

    class Meta:
        db_table = 'app_inventario_productofijo'
        ordering = ['nombre']
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
    
    def __str__(self):
        return self.nombre


class StockBalde(models.Model):
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=3)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)
    is_activo = models.BooleanField(default=True, db_index=True)
    fecha_retiro = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'app_inventario_stockbalde'
        ordering = ['-timestamp']
        indexes = [
            # ✅ ÍNDICES EXISTENTES
            models.Index(fields=['is_activo', 'producto'], name='idx_activo_producto'),
            models.Index(fields=['codigo_barras', 'is_activo'], name='idx_codigo_activo'),
            
            # ⭐ NUEVOS ÍNDICES OPTIMIZADOS
            models.Index(fields=['producto', 'is_activo'], name='idx_producto_activo'),
            models.Index(fields=['is_activo', '-timestamp'], name='idx_activo_ts'),
            models.Index(fields=['codigo_barras', '-timestamp'], name='idx_stock_codigo_ts'),
        ]
        verbose_name = 'Stock Balde'
        verbose_name_plural = 'Stock Baldes'
    
    def __str__(self):
        return f"{self.producto.nombre} - {self.peso}kg - {self.codigo_barras or 's/código'}"


class BocaSalida(models.Model):
    nombre = models.CharField(max_length=100, unique=True, db_index=True)
    
    class Meta:
        db_table = 'app_inventario_bocasalida'
        ordering = ['nombre']
        verbose_name = 'Boca de Salida'
        verbose_name_plural = 'Bocas de Salida'
    
    def __str__(self):
        return self.nombre


class OrigenIngreso(models.Model):
    nombre = models.CharField(max_length=100, unique=True, db_index=True)
    
    class Meta:
        db_table = 'app_inventario_origeningreso'
        ordering = ['nombre']
        verbose_name = 'Origen de Ingreso'
        verbose_name_plural = 'Orígenes de Ingreso'
    
    def __str__(self):
        return self.nombre


class RegistroMovimiento(models.Model):
    TIPO_CHOICES = [
        ("ingreso", "Ingreso"),
        ("salida", "Retiro"),
        ("devolucion", "Devolución"),
    ]
    
    grupo_id = models.IntegerField(db_index=True)
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=3)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    boca_salida = models.CharField(max_length=100, blank=True, null=True)
    
    # Relación origen-destino
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey(BocaSalida, on_delete=models.SET_NULL, blank=True, null=True)
    
    # Trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)

    # Referencia directa al balde físico involucrado en el movimiento.
    # Permite identificar el balde exacto sin depender del codigo_barras
    # (que puede no ser único cuando dos baldes tienen el mismo PLU y peso).
    # SET_NULL: si el balde es eliminado, se conserva el historial del movimiento.
    balde = models.ForeignKey(
        'StockBalde',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='movimientos',
        verbose_name='Balde',
    )

    class Meta:
        db_table = 'app_inventario_registromovimiento'
        ordering = ['-timestamp', '-id']
        indexes = [
            # ✅ ÍNDICES EXISTENTES
            models.Index(fields=['-timestamp', '-id'], name='idx_timestamp_id'),
            models.Index(fields=['grupo_id', '-timestamp'], name='idx_grupo_timestamp'),
            models.Index(fields=['tipo', '-timestamp'], name='idx_tipo_timestamp'),
            
            # ⭐ NUEVOS ÍNDICES OPTIMIZADOS
            # Para búsquedas por producto
            models.Index(fields=['producto', '-timestamp'], name='idx_producto_ts'),
            
            # Para búsquedas por código de barras
            models.Index(fields=['codigo_barras', '-timestamp'], name='idx_mov_codigo_ts'),
            
            # Para filtros combinados (dashboard y reportes)
            models.Index(fields=['tipo', 'producto', '-timestamp'], name='idx_tipo_prod_ts'),
            
            # Para filtros por destino (reportes de salidas)
            models.Index(fields=['destino', 'tipo'], name='idx_destino_tipo'),
            
            # Para queries de rango de fechas con tipo
            models.Index(fields=['timestamp', 'tipo'], name='idx_ts_tipo'),
            
            # Para búsquedas de grupos específicos por tipo
            models.Index(fields=['grupo_id', 'tipo'], name='idx_grupo_tipo'),
        ]
        verbose_name = 'Registro de Movimiento'
        verbose_name_plural = 'Registros de Movimientos'
    
    def __str__(self):
        return f"#{self.grupo_id} {self.tipo} {self.producto.nombre} {self.peso}kg"


class GrupoMovimiento(models.Model):
    TIPO_CHOICES = [
        ("ingreso", "Ingreso"),
        ("salida", "Retiro"),
        ("devolucion", "Devolución"),
    ]
    
    grupo_id = models.IntegerField(primary_key=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey('BocaSalida', on_delete=models.SET_NULL, blank=True, null=True)
    total_peso = models.DecimalField(max_digits=7, decimal_places=2)
    cantidad_items = models.IntegerField(default=0)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'app_inventario_grupomovimiento'
        ordering = ['-fecha']
        indexes = [
            # ⭐ NUEVOS ÍNDICES OPTIMIZADOS
            # Para filtros de historial por fecha y tipo
            models.Index(fields=['-fecha', 'tipo'], name='idx_fecha_tipo'),
            models.Index(fields=['tipo', '-fecha'], name='idx_tipo_fecha'),
            
            # Para reportes por destino
            models.Index(fields=['destino', '-fecha'], name='idx_destino_fecha'),
            models.Index(fields=['destino', 'tipo'], name='idx_destino_tipo_grp'),
            
            # Para búsqueda de grupos en rango de fechas
            models.Index(fields=['fecha', 'tipo'], name='idx_fecha_tipo_grp'),
        ]
        verbose_name = 'Grupo de Movimiento'
        verbose_name_plural = 'Grupos de Movimientos'
    
    def __str__(self):
        return f"Grupo {self.grupo_id} - {self.tipo} - {self.total_peso:.3f} kg"


class ConciliacionBoca(models.Model):
    boca = models.ForeignKey(BocaSalida, on_delete=models.CASCADE)
    mes = models.DateField()  # primer día del mes: YYYY-MM-01
    stock_inicial = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    kg_vendidos = models.DecimalField(max_digits=8, decimal_places=3, default=0)

    class Meta:
        db_table = 'app_inventario_conciliacionboca'
        unique_together = [('boca', 'mes')]
        ordering = ['-mes', 'boca__nombre']
        verbose_name = 'Conciliación'
        verbose_name_plural = 'Conciliaciones'

    def __str__(self):
        return f"{self.boca.nombre} - {self.mes.strftime('%Y-%m')}"


class ConfiguracionSistema(models.Model):
    clave = models.CharField(max_length=50, primary_key=True)
    valor = models.CharField(max_length=200)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'app_inventario_configuracionsistema'
        verbose_name = 'Configuración'
        verbose_name_plural = 'Configuraciones'

    def __str__(self):
        return f"{self.clave} = {self.valor}"
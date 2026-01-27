# models.py - OPTIMIZADO
from django.db import models

class ProductoFijo(models.Model):
    plu = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=255, db_index=True)
    stock_minimo = models.IntegerField(default=5)
    
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
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ ÍNDICE AGREGADO
    
    # Trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)
    is_activo = models.BooleanField(default=True, db_index=True)  # ⚡ ÍNDICE AGREGADO
    fecha_retiro = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'app_inventario_stockbalde'
        ordering = ['-timestamp']
        indexes = [
            # ⚡ ÍNDICE COMPUESTO para búsquedas comunes
            models.Index(fields=['is_activo', 'producto'], name='idx_activo_producto'),
            models.Index(fields=['codigo_barras', 'is_activo'], name='idx_codigo_activo'),
        ]
        verbose_name = 'Stock Balde'
        verbose_name_plural = 'Stock Baldes'
    
    def __str__(self):
        return f"{self.producto.nombre} - {self.peso}kg - {self.codigo_barras or 's/código'}"


class BocaSalida(models.Model):
    nombre = models.CharField(max_length=100, unique=True, db_index=True)  # ⚡ ÍNDICE
    
    class Meta:
        db_table = 'app_inventario_bocasalida'
        ordering = ['nombre']
        verbose_name = 'Boca de Salida'
        verbose_name_plural = 'Bocas de Salida'
    
    def __str__(self):
        return self.nombre


class OrigenIngreso(models.Model):
    nombre = models.CharField(max_length=100, unique=True, db_index=True)  # ⚡ ÍNDICE
    
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
        ("salida", "Retiro")
    ]
    
    grupo_id = models.IntegerField(db_index=True)  # ⚡ ÍNDICE AGREGADO
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=3)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, db_index=True)  # ⚡ ÍNDICE
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ ÍNDICE AGREGADO
    boca_salida = models.CharField(max_length=100, blank=True, null=True)
    
    # Relación origen-destino
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey(BocaSalida, on_delete=models.SET_NULL, blank=True, null=True)
    
    # Trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)
    
    class Meta:
        db_table = 'app_inventario_registromovimiento'
        ordering = ['-timestamp', '-id']
        indexes = [
            # ⚡ ÍNDICES COMPUESTOS para queries comunes
            models.Index(fields=['-timestamp', '-id'], name='idx_timestamp_id'),
            models.Index(fields=['grupo_id', '-timestamp'], name='idx_grupo_timestamp'),
            models.Index(fields=['tipo', '-timestamp'], name='idx_tipo_timestamp'),
        ]
        verbose_name = 'Registro de Movimiento'
        verbose_name_plural = 'Registros de Movimientos'
    
    def __str__(self):
        return f"#{self.grupo_id} {self.tipo} {self.producto.nombre} {self.peso}kg"


class GrupoMovimiento(models.Model):
    TIPO_CHOICES = [
        ("ingreso", "Ingreso"),
        ("salida", "Retiro")
    ]
    
    grupo_id = models.IntegerField(primary_key=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey('BocaSalida', on_delete=models.SET_NULL, blank=True, null=True)
    total_peso = models.DecimalField(max_digits=7, decimal_places=2)
    cantidad_items = models.IntegerField(default=0)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ ÍNDICE AGREGADO
    
    class Meta:
        db_table = 'app_inventario_grupomovimiento'
        ordering = ['-fecha']
        verbose_name = 'Grupo de Movimiento'
        verbose_name_plural = 'Grupos de Movimientos'
    
    def __str__(self):
        return f"Grupo {self.grupo_id} - {self.tipo} - {self.total_peso:.3f} kg"
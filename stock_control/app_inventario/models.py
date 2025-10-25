# models.py
from django.db import models

class ProductoFijo(models.Model):
    plu = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=255, db_index=True)   # index para búsquedas por gusto
    stock_minimo = models.IntegerField(default=5)
    def __str__(self):
        return self.nombre

class StockBalde(models.Model):
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    # 👇 NUEVO: trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)
    is_activo = models.BooleanField(default=True)   # en retiro pasa a False (no se borra)
    fecha_retiro = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.producto.nombre} - {self.peso}kg - {self.codigo_barras or 's/código'}"

class BocaSalida(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.nombre

class OrigenIngreso(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.nombre

class RegistroMovimiento(models.Model):
    grupo_id = models.IntegerField()
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=2)
    tipo = models.CharField(max_length=10, choices=[("ingreso", "Ingreso"), ("salida", "Retiro")])
    timestamp = models.DateTimeField(auto_now_add=True)
    boca_salida = models.CharField(max_length=100, blank=True, null=True)

    # Relación/origen-destino
    origen = models.CharField(max_length=100, blank=True, null=True) 
    destino = models.ForeignKey(BocaSalida, on_delete=models.SET_NULL, blank=True, null=True)

    # 👇 NUEVO: trazabilidad
    codigo_barras = models.CharField(max_length=13, db_index=True, null=True, blank=True)

    def __str__(self):
        return f"#{self.grupo_id} {self.tipo} {self.producto.nombre} {self.peso}kg"

class GrupoMovimiento(models.Model):
    grupo_id = models.IntegerField(primary_key=True)
    tipo = models.CharField(max_length=10, choices=[("ingreso","Ingreso"),("salida","Retiro")])
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey('BocaSalida', on_delete=models.SET_NULL, blank=True, null=True)
    total_peso = models.DecimalField(max_digits=7, decimal_places=2)   # subimos max_digits por seguridad
    cantidad_items = models.IntegerField(default=0)
    fecha = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Grupo {self.grupo_id} - {self.tipo} - {self.total_peso:.2f} kg"

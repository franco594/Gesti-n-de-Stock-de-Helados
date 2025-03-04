from django.db import models

class ProductoFijo(models.Model):
    plu = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=255)
    stock_minimo = models.IntegerField(default=5)

    def __str__(self):
        return self.nombre

class StockBalde(models.Model):
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

class RegistroMovimiento(models.Model):
    grupo_id = models.IntegerField()
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.FloatField()
    tipo = models.CharField(max_length=10, choices=[("ingreso", "Ingreso"), ("retiro", "Retiro")])
    timestamp = models.DateTimeField(auto_now_add=True)

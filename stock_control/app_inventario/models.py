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

    @classmethod
    def crear_movimiento(cls, producto, peso, tipo):
        """
        Crea un nuevo registro de movimiento con un nuevo grupo_id si es necesario.
        """
        ultimo_grupo = cls.objects.all().order_by("-grupo_id").first()
        nuevo_grupo_id = (ultimo_grupo.grupo_id + 1) if ultimo_grupo else 1

        return cls.objects.create(
            grupo_id=nuevo_grupo_id,
            producto=producto,
            peso=peso,
            tipo=tipo
        )

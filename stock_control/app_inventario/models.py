from django.db import models

TIPO_CHOICES = (("ingreso", "Ingreso"), ("retiro", "Retiro"))

class ProductoFijo(models.Model):
    plu = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=255)
    stock_minimo = models.IntegerField(default=5)

    def __str__(self):
        return self.nombre

class StockBalde(models.Model):
    producto = models.ForeignKey(ProductoFijo, on_delete=models.CASCADE)
    peso = models.DecimalField(max_digits=5, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

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
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    boca_salida = models.CharField(max_length=100, blank=True, null=True)  # 👈 importante

    # Relación opcional a BocaSalida como destino o como origen
    origen = models.CharField(max_length=100, blank=True, null=True)  # Para ingresos
    destino = models.ForeignKey(BocaSalida, on_delete=models.SET_NULL, blank=True, null=True)  # Para retiros

    @classmethod
    def crear_movimiento(cls, producto, peso, tipo, origen=None, destino=None):
        ultimo_grupo = cls.objects.all().order_by("-grupo_id").first()
        nuevo_grupo_id = (ultimo_grupo.grupo_id + 1) if ultimo_grupo else 1

        return cls.objects.create(
            grupo_id=nuevo_grupo_id,
            producto=producto,
            peso=peso,
            tipo=tipo,
            origen=origen if tipo == "ingreso" else None,
            destino=destino if tipo == "retiro" else None
        )
    

class GrupoMovimiento(models.Model):
    grupo_id = models.IntegerField(primary_key=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    origen = models.CharField(max_length=100, blank=True, null=True)
    destino = models.ForeignKey('BocaSalida', on_delete=models.SET_NULL, blank=True, null=True)
    total_peso = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    cantidad_items = models.IntegerField(default=0)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Grupo {self.grupo_id} - {self.tipo} - {self.total_peso:.2f} kg"



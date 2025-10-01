# app_inventario/signals.py
import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import RegistroMovimiento, GrupoMovimiento
from .services.printing import print_grupo_movimiento  # 👈 ticket único por grupo

logger = logging.getLogger(__name__)

@receiver(post_save, sender=RegistroMovimiento)
def imprimir_item(sender, instance, created, **kwargs):
    """
    Evita imprimir por balde si pertenece a un grupo.
    Dejalo así para no duplicar tickets.
    """
    if not created:
        return
    if instance.grupo_id:
        return
    # Si algún día querés imprimir un item 'sueltito', llamá acá a tu función de item.
    # from .services.printing import print_movimiento
    # transaction.on_commit(lambda: print_movimiento(instance))

@receiver(post_save, sender=GrupoMovimiento)
def imprimir_ticket_grupo(sender, instance, created, **kwargs):
    """
    Imprime 1 ticket consolidado cuando se crea el GrupoMovimiento.
    _actualizar_total_grupo(...) usa update_or_create, así que en el primer uso 'created' será True.
    """
    if not created:
        return

    def _do_print():
        try:
            # Si querés más de una copia, seteá PRINT_COPIAS en settings/.env
            copias = getattr(__import__('django.conf').conf.settings, "PRINT_COPIAS", 1)
            print_grupo_movimiento(instance.grupo_id, copias=copias)
            logger.info("Ticket de grupo #%s impreso", instance.grupo_id)
        except Exception:
            logger.exception("Error al imprimir ticket del grupo #%s", instance.grupo_id)

    transaction.on_commit(_do_print)

# app_inventario/utils/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app_inventario.utils.task import enviar_reporte_stock

def iniciar_tareas_periodicas():
    """
    Inicia el programador de tareas para ejecutar funciones automáticas.
    """
    scheduler = BackgroundScheduler(
        timezone="America/Argentina/Buenos_Aires"
    )

    # ⏰ Todos los días 23:59 (hora Buenos Aires)
    scheduler.add_job(
        enviar_reporte_stock,
        trigger=CronTrigger(hour=23, minute=59),
        id="reporte_stock_diario_2359",
        replace_existing=True,
        coalesce=True,            # si se salteó una ejecución, junta en una sola
        misfire_grace_time=300,   # 5 min de gracia si el proceso se despierta tarde
        max_instances=1,
    )

    scheduler.start()
    print("🕒 Scheduler iniciado: 'reporte_stock_diario_2359' programado a las 23:59.")

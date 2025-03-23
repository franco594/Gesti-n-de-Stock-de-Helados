import os
from django.apps import AppConfig

class AppInventarioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_inventario'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':
            from apscheduler.schedulers.background import BackgroundScheduler
            from .jobs import backup_postgresql

            scheduler = BackgroundScheduler()
            scheduler.add_job(backup_postgresql, 'cron', hour=10, minute=0)
            scheduler.start()

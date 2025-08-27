from django.apps import AppConfig


class GwizacashConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gwizacash'


from django.apps import AppConfig

class GwizacashConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gwizacash'

    def ready(self):
        from . import scheduler
        scheduler.start_scheduler()

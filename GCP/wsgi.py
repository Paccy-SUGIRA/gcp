import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GCP.settings")
application = get_wsgi_application()

# Import and start scheduler after Django is initialized
from gwizacash.scheduler import start_scheduler
start_scheduler()

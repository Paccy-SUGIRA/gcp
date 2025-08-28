import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GCP.settings")
application = get_wsgi_application()

# Start scheduler after Django is configured
from gwizacash.scheduler import start_scheduler
start_scheduler()

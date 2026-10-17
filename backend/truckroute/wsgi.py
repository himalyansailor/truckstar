import os

from django.core.wsgi import get_wsgi_application

from truckroute import telemetry

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truckroute.settings")
telemetry.setup()
application = get_wsgi_application()

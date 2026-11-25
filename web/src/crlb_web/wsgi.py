"""WSGI entry point of the validation interface (for gunicorn on a server)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crlb_web.settings")
application = get_wsgi_application()

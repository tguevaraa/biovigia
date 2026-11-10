"""Punto de entrada WSGI para servidores de producción (gunicorn, waitress, mod_wsgi)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "biovigia.settings")

application = get_wsgi_application()

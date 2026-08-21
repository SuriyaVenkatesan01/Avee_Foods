"""Root-level WSGI entrypoint.

Render's default start command is ``gunicorn app:app``. The canonical
entrypoint is ``avee_foods.wsgi:application``; this module re-exports it
under the names the default command looks for, so the service boots
whichever start command is configured.
"""

from avee_foods.wsgi import application

app = application

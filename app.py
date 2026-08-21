"""Root-level WSGI entrypoint.

Render's default start command is ``gunicorn app:app``. The canonical
entrypoint is ``avee_foods.wsgi:application``; this module re-exports it
under the names the default command looks for, so the service boots
whichever start command is configured.

It also applies migrations on boot. Migrations belong in the build step
(see build.sh), but running them here means the site comes up correctly
even when the platform's build command has not been changed from its
default. Set DISABLE_STARTUP_MIGRATE=1 once build.sh owns the job.
"""

import logging
import os

from avee_foods.wsgi import application

app = application

logger = logging.getLogger(__name__)

if os.environ.get('DISABLE_STARTUP_MIGRATE') != '1':
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False, verbosity=1)
    except Exception:
        # A boot that cannot migrate should still serve; the request that
        # needs a missing table will report the real problem.
        logger.exception('Startup migrate failed')

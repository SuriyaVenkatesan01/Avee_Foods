"""
WSGI config for avee_foods project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import logging
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "avee_foods.settings")

application = get_wsgi_application()

logger = logging.getLogger(__name__)

# Migrations belong in the build step (see build.sh), but running them here
# means a fresh deploy comes up with its tables even when the platform's
# build command has not been changed from its default. This lives in wsgi.py
# rather than app.py so it runs under either start command. Set
# DISABLE_STARTUP_MIGRATE=1 once build.sh owns the job.
if os.environ.get("DISABLE_STARTUP_MIGRATE") != "1":
    try:
        from django.core.management import call_command

        call_command("migrate", interactive=False, verbosity=1)
    except Exception:
        # A boot that cannot migrate should still serve; the request that
        # needs a missing table will report the real problem.
        logger.exception("Startup migrate failed")

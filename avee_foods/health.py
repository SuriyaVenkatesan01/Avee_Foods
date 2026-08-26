"""Diagnostic endpoint for deployment problems.

Reports what the *running instance* actually sees. It deliberately does not
touch the database, so it still answers when the database is misconfigured --
which is exactly when you need it.

Only booleans, a driver name and the commit SHA are exposed; never the
connection string, the secret key, or any other credential.
"""

import os

from django.conf import settings
from django.http import JsonResponse


def _commit():
    """The commit the host built, as reported by the host itself."""
    for var in (
        "VERCEL_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "SOURCE_VERSION",  # Heroku-style
    ):
        sha = os.environ.get(var, "").strip()
        if sha:
            return {"sha": sha[:7], "from": var}
    return {"sha": None, "from": None}


def healthz(request):
    engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
    return JsonResponse(
        {
            "commit": _commit(),
            "debug": settings.DEBUG,
            # Whether the variable is present, never its value.
            "database_url_set": bool(os.environ.get("DATABASE_URL", "").strip()),
            "db_engine": engine,
            # sqlite on a deployed host is always wrong: the file is gitignored
            # and the filesystem is read-only.
            "db_ok": engine != "sqlite3",
            "allowed_hosts": settings.ALLOWED_HOSTS,
            "media_root": str(settings.MEDIA_ROOT),
            "host_env": {
                v: bool(os.environ.get(v))
                for v in ("VERCEL", "VERCEL_URL", "RENDER", "RENDER_EXTERNAL_HOSTNAME")
            },
        },
        json_dumps_params={"indent": 2},
    )

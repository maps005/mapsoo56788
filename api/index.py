"""Vercel entry point: the Django WSGI application (Vercel's Python runtime serves `app`)."""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planner_site.settings")

from planner_site.wsgi import application  # noqa: E402

PATH_PARAM = "__path"


def app(environ, start_response):
    # vercel.json rewrites every request to /api/index and carries the original
    # path in a query parameter; restore it so Django's URL routing sees it.
    params = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    original = [v for k, v in params if k == PATH_PARAM]
    if original:
        environ["PATH_INFO"] = "/" + original[0].lstrip("/")
        environ["SCRIPT_NAME"] = ""
        environ["QUERY_STRING"] = urlencode([(k, v) for k, v in params if k != PATH_PARAM])
    return application(environ, start_response)

import os
from urllib.parse import parse_qsl, urlencode

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planner_site.settings")
_django = get_wsgi_application()

PATH_PARAM = "__path"


def application(environ, start_response):
    # On Vercel, vercel.json rewrites /api/* requests to /api/index and carries the original path in a query
    # parameter; restore it so Django's URL routing sees it. Requests without the parameter pass through unchanged.
    params = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    original = [v for k, v in params if k == PATH_PARAM]
    if original:
        path = original[0].lstrip("/")
        environ["PATH_INFO"] = "/" + path
        environ["SCRIPT_NAME"] = ""
        # Vercel also adds the rewrite's own `path` parameter; drop it, but keep a `path` the request itself sent
        environ["QUERY_STRING"] = urlencode([(k, v) for k, v in params
                                             if k != PATH_PARAM and not (k == "path" and v == path)])
    return _django(environ, start_response)

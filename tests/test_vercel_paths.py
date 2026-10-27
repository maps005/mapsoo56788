"""Vercel rewrites /api/* to /api/index?__path=...; the WSGI application must route the original path."""
from wsgiref.util import setup_testing_defaults

from planner_site.wsgi import application


def call(path, query=""):
    environ = {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": "GET"}
    setup_testing_defaults(environ)
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen["status"] = int(status.split()[0])
    body = b"".join(application(environ, start_response))
    return seen["status"], body, environ


def test_rewritten_api_path_reaches_the_api(db):
    status, body, environ = call("/api/index", "__path=%2Fapi%2Fai-chat&path=api%2Fai-chat")
    assert status == 401 and b"Please sign in" in body   # the API answered, not a 404 for /api/index
    assert environ["PATH_INFO"] == "/api/ai-chat" and environ["QUERY_STRING"] == ""


def test_rewrite_keeps_the_request_query(db):
    _, _, environ = call("/api/index", "__path=%2Fapi%2Fprojects&path=api%2Fprojects&path=other&q=1")
    assert environ["PATH_INFO"] == "/api/projects"
    assert environ["QUERY_STRING"] == "path=other&q=1"


def test_paths_without_the_rewrite_are_unchanged(db):
    status, _, environ = call("/accounts/login/", "next=%2F")
    assert status == 200 and environ["PATH_INFO"] == "/accounts/login/" and environ["QUERY_STRING"] == "next=%2F"

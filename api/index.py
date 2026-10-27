"""Vercel entry point: the Django WSGI application (Vercel's Python runtime serves `app`)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planner_site.settings")

from planner_site.wsgi import application  # noqa: E402

app = application

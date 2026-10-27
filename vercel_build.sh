#!/bin/sh
# Vercel build step: static files go to public/static (served by Vercel's CDN), then the database is migrated
# and the first administrator is created when the environment variables ask for it.
set -e

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
$PY -m pip install --disable-pip-version-check -q -r requirements.txt

export DJANGO_STATIC_ROOT=public/static
$PY manage.py collectstatic --noinput --clear

if [ -n "${DATABASE_URL:-}" ]; then
  $PY manage.py migrate --noinput
  if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    if $PY manage.py shell -c "import sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists() else 1)"; then
      echo "Administrator $DJANGO_SUPERUSER_USERNAME already exists - you can remove DJANGO_SUPERUSER_PASSWORD"
    else
      $PY manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" \
        --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}"
    fi
  fi
else
  echo "WARNING: DATABASE_URL is not set - the app will use a temporary SQLite database that is lost between requests"
fi

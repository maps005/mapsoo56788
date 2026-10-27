#!/bin/sh
# Vercel build step: static files go to public/static (served by Vercel's CDN), then the database is migrated
# and the first administrator is created when the environment variables ask for it.
set -e

missing=""
[ -n "${DJANGO_SECRET_KEY:-}" ] || missing="$missing DJANGO_SECRET_KEY"
[ -n "${DATABASE_URL:-}${POSTGRES_URL:-}" ] || missing="$missing DATABASE_URL"
if [ -n "$missing" ]; then
  echo "------------------------------------------------------------------------------------------"
  echo "ArchPlanner cannot be deployed yet. Add these in Vercel: Project > Settings > Environment Variables:"
  for v in $missing; do echo "  - $v"; done
  echo "  DJANGO_SECRET_KEY: a long random string (keep it secret)"
  echo "  DATABASE_URL: a PostgreSQL connection string, or connect a Supabase / Neon database under Storage"
  echo "Then redeploy. See DEPLOY-VERCEL.md."
  echo "------------------------------------------------------------------------------------------"
  exit 1
fi

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
# Vercel installs requirements.txt before this script; install only when running the script elsewhere
$PY -c "import django" 2>/dev/null || $PY -m pip install --disable-pip-version-check -q -r requirements.txt

export DJANGO_STATIC_ROOT=public/static
$PY manage.py collectstatic --noinput --clear
# migrations over a direct connection when the integration provides one (the pooled one is for the app)
if [ -n "${POSTGRES_URL_NON_POOLING:-}" ] && [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL="$POSTGRES_URL_NON_POOLING" $PY manage.py migrate --noinput
else
  $PY manage.py migrate --noinput
fi

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  if $PY manage.py shell -c "import sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists() else 1)"; then
    echo "Administrator $DJANGO_SUPERUSER_USERNAME already exists - you can remove DJANGO_SUPERUSER_PASSWORD"
  else
    $PY manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" \
      --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}"
  fi
fi

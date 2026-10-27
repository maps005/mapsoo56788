#!/bin/sh
set -e
python manage.py migrate --noinput
# Optional first administrator, created only if it does not exist yet
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  if python manage.py shell -c "import sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists() else 1)"; then
    echo "Administrator $DJANGO_SUPERUSER_USERNAME already exists - remove DJANGO_SUPERUSER_PASSWORD from .env"
  else
    python manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" \
      --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}"
  fi
fi
exec "$@"

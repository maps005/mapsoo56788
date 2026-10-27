#!/bin/sh
# Creates .env with random secrets for the production stack. Run once on the server.
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  echo ".env already exists - edit it directly or delete it to start again."
  exit 1
fi
printf "Domain name for the planner (e.g. planner.yourcompany.co.ke): "
read DOMAIN
printf "Administrator username [admin]: "
read ADMIN
ADMIN=${ADMIN:-admin}
rand() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "$1"; }
ADMIN_PW=$(rand 20)
umask 077
cat > .env <<EOF
DOMAIN=$DOMAIN
DJANGO_SECRET_KEY=$(rand 64)
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DJANGO_TIME_ZONE=Africa/Nairobi
POSTGRES_DB=ftth
POSTGRES_USER=ftth
POSTGRES_PASSWORD=$(rand 32)
DJANGO_SUPERUSER_USERNAME=$ADMIN
DJANGO_SUPERUSER_PASSWORD=$ADMIN_PW
EOF
echo
echo ".env written (readable only by you)."
echo "First sign-in:  https://$DOMAIN   username: $ADMIN   password: $ADMIN_PW"
echo "Change this password after signing in (top right > Admin > Change password),"
echo "then delete the DJANGO_SUPERUSER_PASSWORD line from .env."

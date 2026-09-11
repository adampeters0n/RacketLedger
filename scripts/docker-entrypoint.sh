#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ -n "${BOOTSTRAP_ADMIN_PASSWORD:-}" ] && [ -n "${BOOTSTRAP_ADMIN_USER:-}" ]; then
  if [ -n "${BOOTSTRAP_NAZEV:-}" ]; then
    python manage.py bootstrap_instance \
      --nazev "${BOOTSTRAP_NAZEV}" \
      --email "${BOOTSTRAP_EMAIL:-}" \
      --create-admin \
      "${BOOTSTRAP_ADMIN_USER}" \
      "${BOOTSTRAP_ADMIN_EMAIL:-admin@example.com}" \
      || true
  else
    python manage.py bootstrap_instance \
      --skip-branding \
      --create-admin \
      "${BOOTSTRAP_ADMIN_USER}" \
      "${BOOTSTRAP_ADMIN_EMAIL:-admin@example.com}" \
      || true
  fi
fi

exec "$@"

#!/bin/sh
set -eu
python manage.py adopt_legacy_schema
python manage.py migrate --fake-initial --noinput
exec supervisord -c /app/supervisord.conf

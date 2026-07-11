#!/bin/sh
set -eu
python manage.py migrate --run-syncdb --noinput
exec supervisord -c /app/supervisord.conf

#!/bin/sh
set -eu
python manage.py migrate --run-syncdb --noinput
python manage.py bootstrap_defaults
exec supervisord -c /app/supervisord.conf

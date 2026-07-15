#!/bin/sh
set -eu
python manage.py migrate --noinput
exec supervisord -c /app/supervisord.conf

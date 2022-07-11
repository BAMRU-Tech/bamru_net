#!/bin/sh

cd $APP_PATH

python manage.py migrate

python manage.py qcluster &

opentelemetry-instrument gunicorn --workers 4 --threads 1 --timeout 30 --access-logfile '/home/LogFiles/gunicorn-access.log' --error-logfile '/home/LogFiles/gunicorn-error.log' --bind=0.0.0.0:8000 --chdir=. bamru_net.wsgi -c deploy/gunicorn.config.py

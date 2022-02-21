#!/bin/sh

cd $APP_PATH

python manage.py migrate

python manage.py qcluster &

gunicorn --workers 4 --threads 1 --timeout 30 --access-logfile '-' --error-logfile '-' --bind=0.0.0.0:8000 --chdir=. bamru_net.wsgi

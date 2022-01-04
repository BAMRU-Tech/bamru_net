#!/bin/sh

cd $APP_PATH

python manage.py migrate

python manage.py qcluster &

gunicorn --timeout 600 --access-logfile '-' --error-logfile '-' --bind=0.0.0.0:8000 --chdir=. bamru_net.wsgi

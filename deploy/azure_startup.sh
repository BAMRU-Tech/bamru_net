#!/bin/sh

cd $APP_PATH

python manage.py migrate

celery worker -A bamru_net --loglevel=INFO >> /home/LogFiles/celery_worker.log &
celery beat -A bamru_net --loglevel=INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler >> /home/LogFiles/celery_beat.log &

gunicorn --timeout 600 --access-logfile '-' --error-logfile '-' --bind=0.0.0.0:8000 --chdir=. bamru_net.wsgi

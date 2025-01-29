#!/bin/sh

cd $APP_PATH

python manage.py migrate

python manage.py qcluster &
QCLUSTER_PID=$!

gunicorn \
  --workers 4 \
  --threads 1 \
  --timeout 30 \
  --access-logfile '/home/LogFiles/gunicorn-access.log' \
  --error-logfile '/home/LogFiles/gunicorn-error.log' \
  --bind=0.0.0.0:8000 \
  --chdir=. \
  bamru_net.wsgi \
  -c deploy/gunicorn.config.py \
  &
GUNICORN_PID=$!

# Wait until either process exits
wait -n $QCLUSTER_PID $GUNICORN_PID

EXIT_CODE=$? # This should be the exit code of whichever process ends first

EXIT_MSG="$(date "+%Y-%m-%d %H:%M:%S") exiting with wait exit code ${EXIT_CODE}"

# Check and append which process ended
EXIT_MSG="${EXIT_MSG}$(
  kill -0 $QCLUSTER_PID 2>/dev/null || echo -n ' Qcluster ended'
)"
EXIT_MSG="${EXIT_MSG}$(
  kill -0 $GUNICORN_PID 2>/dev/null || echo -n ' Gunicorn ended'
)"
echo $EXIT_MSG

# SIGTERM this shell and all its child processes
# This way we don't leave one process running alone if the other one dies
kill -- -$$

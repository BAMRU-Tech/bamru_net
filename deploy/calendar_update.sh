#!/bin/bash
set -e

export GIT_SSH_COMMAND='ssh -i ../id_rsa'
export GIT_AUTHOR_NAME='BAMRU Machine'
export GIT_AUTHOR_EMAIL='info@bamru.org'
export GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME
export GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
export EMAIL=$GIT_AUTHOR_EMAIL

CALENDAR_WEBHOOK=XXX
REPO=/home/bamru/calendar/BAMRU-Org
FILE=calendar.html
DATE=`date --date '1 week ago' '+%Y-%m-01'`
URL=https://bamru.net/event/published/?start_at_after=$DATE
DOWNLOAD=../download.html
HEAD='<!-- BEGIN GENERATED CONTENT -->'
TAIL='<!-- END GENERATED CONTENT -->'

cd $REPO
git pull

curl -o $DOWNLOAD $URL

sed -e "/$HEAD/,/$TAIL/{ /$HEAD/{p; r $DOWNLOAD
        }; /$TAIL/p; d }"  $FILE > ${FILE}.tmp

mv ${FILE}.tmp $FILE

if [ -n "$(git status --porcelain)" ]; then
    echo 'changes found'
    git commit -a -m "update `date`"
    git push
fi
wget -q $CALENDAR_WEBHOOK -O /dev/null

#!/bin/bash
echo 'drop database bnet_development;' | psql -U postgres
echo 'create database bnet_development;' | psql -U postgres
psql -U postgres bnet_development < ~/bnet.sql
rm -f */migrations/00*
./manage.py makemigrations
./manage.py migrate
psql -a -U postgres bnet_development < import.sql
echo "update main_member set is_staff=TRUE, is_superuser=TRUE where id in (367, 559);" | python manage.py dbshell
python manage.py sqlsequencereset main | python manage.py dbshell

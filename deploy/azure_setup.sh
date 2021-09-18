#!/bin/bash
set -e
set -x

NAME=$1
RESOURCEGROUP_NAME=${NAME}-rg
POSTGRES_NAME=${NAME}-db
SERVICEPLAN_NAME=${NAME}-sp
WEBAPP_NAME=${NAME}-app
SLOT=staging

POSTGRES_DB=${NAME}
POSTGRES_USER=${NAME}_admin
POSTGRES_PASSWORD=$2

LOCATION=westus2
SERVICEPLAN_SKU=S1
POSTGRES_SKU=B_Gen5_1

RUNTIME="python:3.6"

: "${SETUP_AZ:=false}"
: "${SETUP_DB:=false}"

if [  $# -lt 2 ]; then 
  echo "Usage: \$0 NAME POSTGRES_PASSWORD"
  exit 1;
fi

# If there are any errors on DB creation, you may need:
#   az extension add --name db-up

if $SETUP_AZ; then
  az group create --name $RESOURCEGROUP_NAME --location $LOCATION

  az postgres up --resource-group $RESOURCEGROUP_NAME --location $LOCATION --sku-name $POSTGRES_SKU --server-name $POSTGRES_NAME --database-name $POSTGRES_DB --admin-user $POSTGRES_USER --admin-password $POSTGRES_PASSWORD --ssl-enforcement Enabled

  az appservice plan create --name $SERVICEPLAN_NAME --resource-group $RESOURCEGROUP_NAME --sku $SERVICEPLAN_SKU --is-linux

  az webapp create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --plan $SERVICEPLAN_NAME --runtime $RUNTIME

  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true
  az webapp config set --ftps-state Disabled --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME

  # az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings #Name=Value
  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings @azure_settings.json

  az webapp deployment slot create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --slot $SLOT --configuration-source $WEBAPP_NAME
  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true -s $SLOT
fi


if $SETUP_DB; then
  # mv gunzip db-2021-05-24--18-17.sql.gz db.sql.gz
  gunzip -k db.sql.gz
  sed -i s/bnet_db/${POSTGRES_USER}/ db.sql
  PGPASSWORD=$POSTGRES_PASSWORD psql --host=${POSTGRES_NAME}.postgres.database.azure.com --port=5432 --username=${POSTGRES_USER}@${POSTGRES_NAME} --dbname=$POSTGRES_DB < db.sql
  rm db.sql.gz
fi

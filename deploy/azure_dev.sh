#!/bin/bash
set -e
set -x

NAME=$1
SLOT=dev
RESOURCEGROUP_NAME=${NAME}-${SLOT}-rg
POSTGRES_NAME=${NAME}-db # shares db server
SERVICEPLAN_NAME=${NAME}-${SLOT}-sp
WEBAPP_NAME=${NAME}-${SLOT}-app
STORAGE_NAME=${NAME}${SLOT} # Can only be [a-z0-9]

POSTGRES_DB=${NAME}
POSTGRES_USER=${NAME}_admin
POSTGRES_PASSWORD=$2
SLOT_POSTGRES_DB=${NAME}${SLOT}
SLOT_POSTGRES_USER=${NAME}_${SLOT}_admin
SLOT_POSTGRES_PASSWORD=$3

LOCATION=westus
SERVICEPLAN_SKU=F1

RUNTIME="python:3.8"

: "${SETUP_AZ:=false}"
: "${SETUP_CERT:=false}"
: "${SETUP_STORE:=false}"
: "${SETUP_DB:=false}"
: "${SETUP_CONFIG:=false}"
: "${SETUP_GITHUB:=false}"

if [  $# -lt 3 ]; then
  echo "Usage: \$0 NAME POSTGRES_PASSWORD SLOT_POSTGRES_PASSWORD"
  exit 1;
fi

if $SETUP_AZ; then
  az group create --name $RESOURCEGROUP_NAME --location $LOCATION

  #az postgres db create --resource-group $RESOURCEGROUP_NAME --server-name $POSTGRES_NAME  --name ${SLOT_POSTGRES_DB}


  az appservice plan create --name $SERVICEPLAN_NAME --resource-group $RESOURCEGROUP_NAME --sku $SERVICEPLAN_SKU --is-linux --location $LOCATION
  az webapp create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --plan $SERVICEPLAN_NAME --runtime $RUNTIME

  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true
  az webapp config set --ftps-state Disabled --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --startup-file "deploy/azure_startup.sh"
  az webapp log config -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --docker-container-logging filesystem --application-logging filesystem
fi


if $SETUP_STORE; then
    az storage account create --name $STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --access-tier Hot --kind StorageV2  --location $LOCATION --min-tls-version TLS1_2 --sku Standard_RAGRS
    az storage container create --name media --account-name $STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --public-access off
    az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}.azurewebsites.net" --account-name $STORAGE_NAME
fi


if $SETUP_DB; then
    CONNECT="--host=${POSTGRES_NAME}.postgres.database.azure.com --port=5432"
    CONNECT_ADMIN="$CONNECT --username=${POSTGRES_USER}@${POSTGRES_NAME}"
    CONNECT_NEW="$CONNECT --username=${SLOT_POSTGRES_USER}@${POSTGRES_NAME}"
    PGSSLMODE=require
    PGPASSWORD="$POSTGRES_PASSWORD" psql $CONNECT_ADMIN ${POSTGRES_DB} <<EOF
    DROP ROLE ${SLOT_POSTGRES_USER};
    CREATE ROLE ${SLOT_POSTGRES_USER} WITH LOGIN NOSUPERUSER INHERIT CREATEDB NOCREATEROLE NOREPLICATION PASSWORD '${SLOT_POSTGRES_PASSWORD}';
EOF
    PGPASSWORD="$POSTGRES_PASSWORD" psql $CONNECT_ADMIN ${POSTGRES_DB} <<EOF
    CREATE DATABASE ${SLOT_POSTGRES_DB};
EOF
    #PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --format=custom --file=db.dump $CONNECT_ADMIN --dbname=$POSTGRES_DB
    PGPASSWORD="$SLOT_POSTGRES_PASSWORD" pg_restore $CONNECT_NEW -d ${SLOT_POSTGRES_DB} --no-owner db.dump
fi


AZURE_STORAGE_KEY=$(az storage account keys list  --account-name $STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --query [0].value -o tsv)

if $SETUP_CONFIG; then
  sed -e "s#X_AZURE_STORAGE_KEY#$AZURE_STORAGE_KEY#g" \
      -e "s/X_AZURE_STORAGE_ACCOUNT_NAME/$STORAGE_NAME/g" \
      -e "s/X_POSTGRES_HOST/${POSTGRES_NAME}.postgres.database.azure.com/g" \
      -e "s/X_POSTGRES_DB/$SLOT_POSTGRES_DB/g" \
      -e "s/X_POSTGRES_PASS/$SLOT_POSTGRES_PASSWORD/g " \
      -e "s/X_POSTGRES_USER/${SLOT_POSTGRES_USER}@${POSTGRES_NAME}/g" \
      -e "s/X_HOSTNAME/${WEBAPP_NAME}.azurewebsites.net/g" \
      -e "s/X_ALLOWED_HOST/${WEBAPP_NAME}.azurewebsites.net/g" \
      azure_settings.json > processed-dev.json

  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n ${WEBAPP_NAME} --settings @processed-dev.json @azure_dev_secrets.json
fi


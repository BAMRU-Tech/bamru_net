#!/bin/bash
set -e
set -x

NAME=$1
SLOT=staging
RESOURCEGROUP_NAME=${NAME}-rg
POSTGRES_NAME=${NAME}-db
SERVICEPLAN_NAME=${NAME}-sp
WEBAPP_NAME=${NAME}-app
STORAGE_NAME=${NAME}
SLOT_STORAGE_NAME=${NAME}${SLOT} # Can only be [a-z0-9]
HOSTNAME=$2
SLOT_HOSTNAME=${SLOT}.${HOSTNAME}

POSTGRES_DB=${NAME}
SLOT_POSTGRES_DB=${NAME}-${SLOT}
POSTGRES_USER=${NAME}_admin
POSTGRES_PASSWORD=$3

LOCATION=westus
SERVICEPLAN_SKU=S1
POSTGRES_SKU=B_Gen5_1

RUNTIME="python:3.8"

: "${SETUP_AZ:=false}"
: "${SETUP_CERT:=false}"
: "${SETUP_STORE:=false}"
: "${SETUP_DB:=false}"
: "${SETUP_CONFIG:=false}"
: "${SETUP_GITHUB:=false}"

if [  $# -lt 3 ]; then
  echo "Usage: \$0 NAME HOSTNAME POSTGRES_PASSWORD"
  exit 1;
fi

# If there are any errors on DB creation, you may need:
#   az extension add --name db-up

if $SETUP_AZ; then
  az group create --name $RESOURCEGROUP_NAME --location $LOCATION

  az postgres up --resource-group $RESOURCEGROUP_NAME --location $LOCATION --sku-name $POSTGRES_SKU --server-name $POSTGRES_NAME --database-name $POSTGRES_DB --admin-user $POSTGRES_USER --admin-password $POSTGRES_PASSWORD --ssl-enforcement Enabled

  az postgres db create --resource-group $RESOURCEGROUP_NAME --server-name $POSTGRES_NAME  --name ${SLOT_POSTGRES_DB}

  az appservice plan create --name $SERVICEPLAN_NAME --resource-group $RESOURCEGROUP_NAME --sku $SERVICEPLAN_SKU --is-linux --location $LOCATION

  az webapp create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --plan $SERVICEPLAN_NAME --runtime $RUNTIME

  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true
  az webapp config set --ftps-state Disabled --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --startup-file "deploy/azure_startup.sh"
  az webapp log config -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --docker-container-logging filesystem --application-logging filesystem


  # az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings #Name=Value
  # az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings @azure_settings.json

  az webapp deployment slot create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --slot $SLOT --configuration-source $WEBAPP_NAME
  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true -s $SLOT

  # Create a dev slot with git local deploy
  # az webapp deployment slot create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --slot dev --configuration-source $WEBAPP_NAME
  # az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true -s dev
  # az webapp deployment source config-local-git --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --slot dev
fi

if $SETUP_CERT; then
  # Create and bind a free certificate
  az webapp config hostname add --webapp-name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --hostname $HOSTNAME
  az webapp config hostname add --webapp-name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --hostname $SLOT_HOSTNAME
  #thumbprint=$(az webapp config ssl create  --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --hostname $HOSTNAME  --output tsv --query thumbprint)
  thumbprint_slot=$(az webapp config ssl create  --name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --hostname $SLOT_HOSTNAME  --output tsv --query thumbprint)
  echo "If the thumbprint is not ready, wait a few minutes and re-try."
  az webapp config ssl bind --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --certificate-thumbprint $thumbprint --ssl-type SNI
  az webapp config ssl bind --name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --certificate-thumbprint $thumbprint_slot --ssl-type SNI
fi

if $SETUP_STORE; then
  for Name in $STORAGE_NAME $SLOT_STORAGE_NAME; do
    az storage account create --name $Name --resource-group $RESOURCEGROUP_NAME --access-tier Hot --kind StorageV2  --location $LOCATION --min-tls-version TLS1_2 --sku Standard_RAGRS
    az storage account blob-service-properties update --resource-group $RESOURCEGROUP_NAME --account-name $Name \
      --enable-delete-retention true \
      --delete-retention-days 14 \
      --enable-versioning true \
      --enable-change-feed true \
      --enable-restore-policy true \
      --restore-days 7 \
      --enable-container-delete-retention true \
      --container-delete-retention-days 7
    az storage container create --name media --account-name $Name --resource-group $RESOURCEGROUP_NAME --public-access off
    az storage container create --name static --account-name $Name --resource-group $RESOURCEGROUP_NAME --public-access container
  done
  exit
  az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}.azurewebsites.net" --account-name $STORAGE_NAME
  az storage cors add --methods GET --service b --origins "https://${HOSTNAME}" --account-name $STORAGE_NAME
  
  az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}-${SLOT}.azurewebsites.net" --account-name $SLOT_STORAGE_NAME
  az storage cors add --methods GET --service b --origins "https://${SLOT}.${HOSTNAME}" --account-name $SLOT_STORAGE_NAME
  
  # az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}-dev.azurewebsites.net" --account-name $STORAGE_NAME
fi


if $SETUP_DB; then
  # mv gunzip db-2021-05-24--18-17.sql.gz db.sql.gz
  gunzip -k db.sql.gz
  sed -i s/bnet_db/${POSTGRES_USER}/ db.sql
  PGPASSWORD=$POSTGRES_PASSWORD psql --host=${POSTGRES_NAME}.postgres.database.azure.com --port=5432 --username=${POSTGRES_USER}@${POSTGRES_NAME} --dbname=$POSTGRES_DB < db.sql
  rm db.sql
fi


AZURE_STORAGE_KEY=$(az storage account keys list  --account-name $STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --query [0].value -o tsv)
SLOT_AZURE_STORAGE_KEY=$(az storage account keys list  --account-name $SLOT_STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --query [0].value -o tsv)

if $SETUP_CONFIG; then
  sed -e "s#X_AZURE_STORAGE_KEY#$SLOT_AZURE_STORAGE_KEY#g" \
      -e "s/X_AZURE_STORAGE_ACCOUNT_NAME/$SLOT_STORAGE_NAME/g" \
      -e "s/X_HOSTNAME/${WEBAPP_NAME}-${SLOT}.azurewebsites.net/g" \
      -e "s/X_ALLOWED_HOST/${SLOT_HOSTNAME},${WEBAPP_NAME}-${SLOT}.azurewebsites.net/g" \
      -e "s/X_POSTGRES_HOST/${POSTGRES_NAME}.postgres.database.azure.com/g" \
      -e "s/X_POSTGRES_DB/$SLOT_POSTGRES_DB/g" \
      -e "s/X_POSTGRES_PASS/$POSTGRES_PASSWORD/g " \
      -e "s/X_POSTGRES_USER/${POSTGRES_USER}@${POSTGRES_NAME}/g" \
      azure_settings.json > processed-${SLOT}.json

  sed -e "s#X_AZURE_STORAGE_KEY#$AZURE_STORAGE_KEY#g" \
      -e "s/X_AZURE_STORAGE_ACCOUNT_NAME/$STORAGE_NAME/g" \
      -e "s/X_HOSTNAME/${WEBAPP_NAME}.azurewebsites.net/g" \
      -e "s/X_ALLOWED_HOST/${HOSTNAME},${WEBAPP_NAME}.azurewebsites.net/g" \
      -e "s/X_POSTGRES_HOST/${POSTGRES_NAME}.postgres.database.azure.com/g" \
      -e "s/X_POSTGRES_DB/$POSTGRES_DB/g" \
      -e "s/X_POSTGRES_PASS/$POSTGRES_PASSWORD/g " \
      -e "s/X_POSTGRES_USER/${POSTGRES_USER}@${POSTGRES_NAME}/g" \
      azure_settings.json > processed.json

  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n ${WEBAPP_NAME} --slot ${SLOT} --settings @processed-${SLOT}.json @azure_secrets.json
  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n ${WEBAPP_NAME} --settings @processed.json @azure_secrets.json

  # rm -f processed.json processed-${SLOT}.json
fi

echo Storage command:
echo az storage blob upload-batch -d media -s . --account-name $STORAGE_NAME --account-key \'$AZURE_STORAGE_KEY\'

echo DB Backup Command:
echo pg_dump -Fc -v \"host=${POSTGRES_NAME}.postgres.database.azure.com port=5432 user=${POSTGRES_USER}@${POSTGRES_NAME} password=${POSTGRES_PASSWORD} dbname=$POSTGRES_DB sslmode=require\" -f backup.dump

echo psql -h ${POSTGRES_NAME}.postgres.database.azure.com -U ${POSTGRES_USER}@${POSTGRES_NAME}  -v sslmode=require $POSTGRES_DB

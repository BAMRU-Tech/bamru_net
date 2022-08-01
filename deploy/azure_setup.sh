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
POSTGRES_RO_USER=${NAME}_readonly
POSTGRES_PASSWORD=$3
POSTGRES_RO_PASSWORD=$4

LOCATION=westus
SERVICEPLAN_SKU=P1V3
POSTGRES_TIER=Burstable
POSTGRES_SKU=Standard_B2s
POSTGRES_VERSION=14

RUNTIME="python:3.9"

: "${SETUP_AZ:=false}"
: "${SETUP_CERT:=false}"
: "${SETUP_CERT_SLOT:=false}"
: "${SETUP_STORE:=false}"
: "${SETUP_DB:=false}"
: "${SETUP_CONFIG:=false}"

if [  $# -lt 4 ]; then
  echo "Usage: \$0 NAME HOSTNAME POSTGRES_PASSWORD POSTGRES_RO_PASSWORD"
  exit 1;
fi

# If there are any errors on DB creation, you may need:
#   az extension add --name db-up

if $SETUP_AZ; then
  az group create --name $RESOURCEGROUP_NAME --location $LOCATION

  az postgres flexible-server create --resource-group $RESOURCEGROUP_NAME --location $LOCATION --tier $POSTGRES_TIER --sku-name $POSTGRES_SKU --name $POSTGRES_NAME --database-name $POSTGRES_DB --admin-user $POSTGRES_USER --admin-password "$POSTGRES_PASSWORD" --version $POSTGRES_VERSION --public-access 0.0.0.0 --storage-size 32


  az appservice plan create --name $SERVICEPLAN_NAME --resource-group $RESOURCEGROUP_NAME --sku $SERVICEPLAN_SKU --is-linux --location $LOCATION

  az webapp create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --plan $SERVICEPLAN_NAME --runtime $RUNTIME

  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true
  az webapp config set --ftps-state Disabled --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --startup-file "deploy/azure_startup.sh"
  az webapp log config -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --docker-container-logging filesystem --application-logging filesystem


  # az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings #Name=Value
  # az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n $WEBAPP_NAME --settings @azure_settings.json

  az webapp deployment slot create --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --slot $SLOT --configuration-source $WEBAPP_NAME
  az webapp update -g $RESOURCEGROUP_NAME -n $WEBAPP_NAME --https-only true -s $SLOT
fi

if $SETUP_CERT; then
  # Create and bind a free certificate
  az webapp config hostname add --webapp-name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --hostname $HOSTNAME
  thumbprint=''
  while [[ -z "$thumbprint" ]]; do
    thumbprint=$(az webapp config ssl create  --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --hostname $HOSTNAME  --output tsv --query thumbprint)
    [[ -z "$thumbprint" ]] && echo "no thumbprint yet, waiting a bit..." && sleep 5
  done
  az webapp config ssl bind --name $WEBAPP_NAME --resource-group $RESOURCEGROUP_NAME --certificate-thumbprint $thumbprint --ssl-type SNI
fi
if $SETUP_CERT_SLOT; then
  # Create and bind a free certificate
  az webapp config hostname add --webapp-name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --hostname $SLOT_HOSTNAME
  thumbprint_slot=''
  while [[ -z "$thumbprint_slot" ]]; do
    thumbprint_slot=$(az webapp config ssl create  --name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --hostname $SLOT_HOSTNAME  --output tsv --query thumbprint)
    [[ -z "$thumbprint_slot" ]] && echo "no thumbprint yet, waiting a bit..." && sleep 5
  done
  az webapp config ssl bind --name $WEBAPP_NAME -s $SLOT --resource-group $RESOURCEGROUP_NAME --ssl-type SNI --certificate-thumbprint $thumbprint_slot
fi

if $SETUP_STORE; then
  for Name in $STORAGE_NAME; do
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
  az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}.azurewebsites.net" --account-name $STORAGE_NAME
  az storage cors add --methods GET --service b --origins "https://${HOSTNAME}" --account-name $STORAGE_NAME
  
  az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}-${SLOT}.azurewebsites.net" --account-name $STORAGE_NAME
  az storage cors add --methods GET --service b --origins "https://${SLOT}.${HOSTNAME}" --account-name $STORAGE_NAME
  
  # az storage cors add --methods GET --service b --origins "https://${WEBAPP_NAME}-dev.azurewebsites.net" --account-name $STORAGE_NAME
fi

PSQL="psql --host=${POSTGRES_NAME}.postgres.database.azure.com --port=5432 --username=${POSTGRES_USER} --dbname=$POSTGRES_DB"
if $SETUP_DB; then
  # mv gunzip db-2021-05-24--18-17.sql.gz db.sql.gz
  gunzip -k db.sql.gz
  sed -i s/bnet_db/${POSTGRES_USER}/ db.sql
  PGSSLMODE=require PGPASSWORD="$POSTGRES_PASSWORD" $PSQL < db.sql
  rm db.sql
  PGSSLMODE=require PGPASSWORD="$POSTGRES_PASSWORD" $PSQL <<EOF
    CREATE ROLE ${POSTGRES_RO_USER} WITH LOGIN ENCRYPTED PASSWORD '${POSTGRES_RO_PASSWORD}';
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_RO_USER};
    GRANT USAGE ON SCHEMA public TO ${POSTGRES_RO_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${POSTGRES_RO_USER};
    GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ${POSTGRES_RO_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
       GRANT SELECT ON TABLES TO ${POSTGRES_RO_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
       GRANT SELECT ON SEQUENCES TO ${POSTGRES_RO_USER};
EOF
fi


AZURE_STORAGE_KEY=$(az storage account keys list  --account-name $STORAGE_NAME --resource-group $RESOURCEGROUP_NAME --query [0].value -o tsv)

if $SETUP_CONFIG; then
  sed -e "s#X_AZURE_STORAGE_KEY#$AZURE_STORAGE_KEY#g" \
      -e "s/X_AZURE_STORAGE_ACCOUNT_NAME/$STORAGE_NAME/g" \
      -e "s/X_POSTGRES_HOST/${POSTGRES_NAME}.postgres.database.azure.com/g" \
      -e "s/X_POSTGRES_DB/$POSTGRES_DB/g" \
      -e "s/X_POSTGRES_PASS/$POSTGRES_PASSWORD/g " \
      -e "s/X_POSTGRES_USER/${POSTGRES_USER}/g" \
      azure_settings.json > processed-common.json

  sed -e "s/X_HOSTNAME/${SLOT_HOSTNAME}/g" \
      -e "s/X_ALLOWED_HOST/${SLOT_HOSTNAME},${WEBAPP_NAME}-${SLOT}.azurewebsites.net/g" \
      processed-common.json > processed-${SLOT}.json

  sed -e "s/X_HOSTNAME/${HOSTNAME}/g" \
      -e "s/X_ALLOWED_HOST/${HOSTNAME},${WEBAPP_NAME}.azurewebsites.net/g" \
      processed-common.json > processed.json

  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n ${WEBAPP_NAME} --slot ${SLOT} --settings @processed-${SLOT}.json @azure_secrets.json
  az webapp config appsettings set --resource-group $RESOURCEGROUP_NAME -n ${WEBAPP_NAME} --settings @processed.json @azure_secrets.json

  # rm -f processed.json processed-${SLOT}.json
fi

echo Storage command:
echo az storage blob upload-batch -d media -s . --account-name $STORAGE_NAME --account-key \'$AZURE_STORAGE_KEY\'

echo DB Backup Command:
echo pg_dump -Fc -v \"host=${POSTGRES_NAME}.postgres.database.azure.com port=5432 user=${POSTGRES_RO_USER} password=${POSTGRES_RO_PASSWORD} dbname=$POSTGRES_DB sslmode=require\" -f backup.dump

echo psql -h ${POSTGRES_NAME}.postgres.database.azure.com -U ${POSTGRES_USER}  -v sslmode=require $POSTGRES_DB

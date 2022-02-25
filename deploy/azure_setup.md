# Bamru Azure setup - inital runbook

## Preliminary steps

* Install `az` (e.g. `brew install azure-cli` on macos)
* `az login`
* `az extension add --name db-up`
  * I did not have success getting this to install on macos. After trying for a while I gave up and spun up a linux VM where it installed smoothly.
* Install `pqsl` (e.g. `postgresql-client` package)

## Prepare data
Ensure the following are present in the `deploy` directory:
* `db.sql.gz`
* `azure_secrets.json`

## Initial setup

### Generate a strong password for postgres
Do this however you like best.

## Set up everything other than the certificate:
`SETUP_AZ=true SETUP_STORE=true SETUP_DB=true SETUP_CONFIG=true ./azure_setup.sh bamrunet bamru.info 'XXX_MAIN_DATABASE_PASSWORD_XXX'`

## Upload storage data
Log into prod, enter the vagrant vm, become bamru user

`cd ~bamru/system`

Then...

**option 1:**
* `az login`
* `sudo az storage blob upload-batch -d media -s . --account-name bamrunet --account-key ''`
  * Yes, this command has an empty account key. It's correct.
  * (ignore warnings that it is looking up account key)

**option 2:**
* copy and run the storage command from the azure_setup output

## Cert setup
Go to namecheap and set:
  * A record of root to prod IP
  * CNAME of staging to staging hostname (bamrunet-app-staging.azurewebsites.net)
  * asuid and asuid.staging TXT records containing 1472EE3DA91B69279E1CD100F11ED459BB1671EC9BB630D5C4F735FB58D27C14

`SETUP_CERT=true ./azure_setup.sh bamrunet bamru.info bogus_unused_database_password`

It will take some time for thumbnails to be done.

If you get other errors, check the namecheap config and/or try in the GUI for better messages.

## Deployment from github
* Go to "Deployment Center" in app/staging on portal.azure.com
* Select GitHub
* Authorize
* "Manage publish profile" -> Download
* Go to the github repo -> github.com/.../settings/secrets/actions
* Save the downloaded file as AZUREAPPSERVICE_PUBLISHPROFILE

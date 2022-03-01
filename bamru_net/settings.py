"""
Django settings for bamru_net project.

Generated by 'django-admin startproject' using Django 2.0.3.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import os
import raven
from distutils.util import strtobool
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'main/static'),
)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = strtobool(os.environ['DJANGO_DEBUG'])

ALLOWED_HOSTS = os.environ['DJANGO_ALLOWED_HOST'].split(',') + ['localhost', '127.0.0.1']


# Application definition

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'anymail',
    'bootstrap4',
    'django_filters',
    'django_q',
    'django_twilio',
    'dynamic_preferences',
    'imagekit',
    'oidc_provider',
    'raven.contrib.django.raven_compat',
    'rest_framework',
    'rules.apps.AutodiscoverRulesConfig',
    'social_django',
    'storages',
    'main',
    'main.templatetags.filters',
    'django.contrib.admin',  # Must be after main for templates
]

AUTHENTICATION_BACKENDS = [
    'social_core.backends.google.GoogleOAuth2',
    'rules.permissions.ObjectPermissionBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.coreapi.AutoSchema'
}

ROOT_URLCONF = 'bamru_net.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dynamic_preferences.processors.global_preferences',
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',
                'main.context_processors.dsn',
            ],
        },
    },
]

WSGI_APPLICATION = 'bamru_net.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['DJANGO_DB_NAME'],
        'USER': os.environ['DJANGO_DB_USER'],
        'PASSWORD': os.environ['DJANGO_DB_PASS'],
        'HOST': os.environ['DJANGO_DB_HOST'],
        'OPTIONS': {'sslmode': os.environ.get('DJANGO_DB_SSLMODE', 'prefer')},
        'CONN_MAX_AGE': 600,
    }
}

SOCIAL_AUTH_URL_NAMESPACE = 'social'
SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.social_user',
    'main.lib.social_auth.validate_login',
    'social_core.pipeline.social_auth.associate_user',
)
SOCIAL_AUTH_USER_MODEL = 'main.Member'
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.environ.get('SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.environ.get('SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS = ['bamru.org']

AUTH_USER_MODEL = 'main.Member'

# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.BCryptPasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]

# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/Los_Angeles'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

AZURE_STORAGE_KEY = os.environ.get('AZURE_STORAGE_KEY', False)
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get('AZURE_STORAGE_ACCOUNT_NAME', False)
AZURE_MEDIA_CONTAINER = os.environ.get('AZURE_MEDIA_CONTAINER', 'media')
AZURE_STATIC_CONTAINER = os.environ.get('AZURE_STATIC_CONTAINER', 'static')

if AZURE_STORAGE_KEY:
    DEFAULT_FILE_STORAGE = 'bamru_net.backend.AzureMediaStorage'
    #STATICFILES_STORAGE = 'bamru_net.backend.AzureStaticStorage'

    # AZURE_CUSTOM_DOMAIN = '{}.azureedge.net'.format(AZURE_STORAGE_ACCOUNT_NAME)  # CDN URL
    AZURE_CUSTOM_DOMAIN = '{}.blob.core.windows.net'.format(AZURE_STORAGE_ACCOUNT_NAME)  # Files URL

    #STATIC_URL = 'https://{}/{}/'.format(AZURE_CUSTOM_DOMAIN, AZURE_STATIC_CONTAINER)
    MEDIA_URL = 'https://{}/{}/'.format(AZURE_CUSTOM_DOMAIN, AZURE_MEDIA_CONTAINER)

    STATIC_URL = '/static/'
    STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
else:
    STATIC_URL = '/static/'
    STATIC_ROOT = os.environ.get('DJANGO_STATIC_ROOT')

    MEDIA_URL = '/system/'
    MEDIA_ROOT = os.environ.get('MEDIA_ROOT', 'system/')
USE_NGINX_ACCEL_REDIRECT = not (AZURE_STORAGE_KEY or DEBUG)

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
OIDC_USERINFO = 'main.oidc_provider_settings.userinfo'

# Raven config for Sentry.io logging
RELEASE = os.environ.get('GIT_SHA', '0') # TODO raven.fetch_git_sha(os.path.abspath(BASE_DIR))
if strtobool(os.environ.get('USE_RAVEN', 'False')):
    RAVEN_CONFIG = {
        'dsn': os.environ['RAVEN_DSN'],
        # If you are using git, you can also automatically configure the
        # release based on the git info.
        'release': RELEASE,
    }
JAVASCRIPT_DSN = os.environ.get('JAVASCRIPT_DSN','')

TWILIO_SMS_FROM = [e.strip() for e in os.environ['TWILIO_SMS_FROM'].split(',')]
HOSTNAME = os.environ['DJANGO_HOSTNAME']
# Needed for django-oidc-provider
SITE_URL = '{}://{}'.format(os.environ.get('DJANGO_SCHEMA', 'https'), HOSTNAME)

# Temporary fix for #128
DJANGO_TWILIO_FORGERY_PROTECTION=False

if os.environ.get('MESSAGE_FILE_PATH'):
    EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
    EMAIL_FILE_PATH = os.environ['MESSAGE_FILE_PATH']
    SMS_FILE_PATH = EMAIL_FILE_PATH
else:
    EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
    SMS_FILE_PATH = None

ANYMAIL = {
    'WEBHOOK_SECRET': os.environ['MAILGUN_WEBHOOK_SECRET'],
    'MAILGUN_API_KEY': os.environ['MAILGUN_API_KEY'],
}
MAILGUN_EMAIL_FROM = os.environ['MAILGUN_EMAIL_FROM']
DEFAULT_FROM_EMAIL = os.environ['MAILGUN_EMAIL_FROM']

# Used for tests
GOOGLE_CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', '')

Q_CLUSTER = {
    'workers': 1,
    'timeout': 90,  # seconds until task is killed
    'retry': 120,  # seconds until task restarted (retry > timeout)
    'orm': 'default', # Use Django database as a broker
    'poll': 2,  # 2 second poll time if blocking DB access not available
}

from django.utils.log import DEFAULT_LOGGING
LOG_ROOT = os.environ['LOG_ROOT']
LOGGING_CONFIG = None
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'root': {
        'handlers': ['sentry', 'file'],
    },
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(name)s:%(module)s:%(lineno)d '
                      '%(process)d %(thread)d %(message)s'
        },
        'django.server': DEFAULT_LOGGING['formatters']['django.server'],
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': os.path.join(LOG_ROOT, 'django.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 90,
        },
        'sentry': {
            'level': 'WARNING',
            'class': 'raven.contrib.django.raven_compat.handlers.SentryHandler',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        },
        'django.server': DEFAULT_LOGGING['handlers']['django.server'],
    },
    'loggers': {
        'django.db.backends': {
            'level': 'ERROR',
            'handlers': ['console'],
            'propagate': False,
        },
        'raven': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
        'sentry.errors': {
            'level': 'DEBUG',
            'handlers': ['console'],
            'propagate': False,
        },
        # Default runserver request logging
        'django.server': DEFAULT_LOGGING['loggers']['django.server'],
        # Project logging
        'main': {
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'handlers': ['console', 'sentry', 'file'],
            'propagate': False,
        },
    },
}

import logging.config
logging.config.dictConfig(LOGGING)

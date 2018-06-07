# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.dispatch import receiver
from django.urls import reverse
from django_twilio.client import twilio_client

#from datetime import datetime

from anymail.message import AnymailMessage
from anymail.signals import tracking
import phonenumbers
import logging
logger = logging.getLogger(__name__)

from .base import BaseModel
from .member import Member, Role, Phone, Email, Address, EmergencyContact, OtherInfo
from .event import Event, Period, Participant
from .message import Message, Distribution, OutboundSms, InboundSms, OutboundEmail

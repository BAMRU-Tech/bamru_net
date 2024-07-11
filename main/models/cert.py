# Cert-related models

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import Truncator

from .base import BasePositionModel
from .member import Member

from dataclasses import dataclass
from datetime import timedelta
from functools import cache
import jinja2

import logging
logger = logging.getLogger(__name__)

@dataclass
class DisplayCert:
    cert = None
    type: str = None
    expires_on = None
    description: str = ''
    color: str = ''
    count: int = 0

    def __str__(self):
        result = str(self.cert)
        if self.count > 1:
            result += ' *'
        return result


class CertType(BasePositionModel):
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True,
                                    help_text='Optional shorter name for display.')
    max_display_length = models.IntegerField(default=255)
    responsive_priority = models.IntegerField(default=1)
    show_combined = models.BooleanField(default=False)
    has_earned_date = models.BooleanField(default=True)
    has_expiration_date = models.BooleanField(default=True)
    has_description = models.BooleanField(default=True)
    has_link = models.BooleanField(default=False)
    has_file = models.BooleanField(default=True)
    hide_in_summary = models.BooleanField(default=False)  # Do not show on list page
    display_only = models.BooleanField(default=False)  # Do not add certs of this type
    template = models.TextField(blank=True)
    help_text = models.TextField(blank=True)

    def __str__(self):
        return self.name

    @classmethod
    @property
    def display_cert_types(cls):
        return cls.objects.filter(hide_in_summary=False)

    @cache
    def compiled_template(self, env):
        try:
            return env.from_string(self.template)
        except jinja2.exceptions.TemplateSyntaxError as e:
            return env.from_string(str(e))

    def get_display_cert(self, cert_set):
        current = DisplayCert()
        current.type = self.name
        combined_descriptions = []
        includes_other = False
        for cert in cert_set:
            if not cert.subtype or cert.subtype.type != self:
                continue
            if cert.subtype.is_other:
                description = cert.description
            else:
                description = cert.subtype.name
            if self.show_combined:
                if cert.subtype.is_other:
                    includes_other = True
                    continue
                combined_descriptions.append((cert.subtype.position, description))
            if (not current.cert or
                  (current.cert.is_expired and not cert.is_expired) or
                  (current.cert.subtype.position > cert.subtype.position)
            ):
                current.cert = cert
                current.color = cert.color
                current.count += 1
                current.description = Truncator(description).chars(
                    self.max_display_length)
        if self.show_combined:
            sorted_descs = [x[1] for x in
                            sorted(combined_descriptions, key=lambda tup: tup[0])]
            if includes_other:
                sorted_descs.append('...')
            current.description = " | ".join(sorted_descs)
            current.count = 1  # since combined, display as 1
        return current


class CertSubType(BasePositionModel):
    type = models.ForeignKey(CertType, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    is_other = models.BooleanField(default=False)

    def __str__(self):
        return "{} - {}".format(self.type.name, self.name)

def cert_upload_path_handler(instance, filename):
    return "certs/{id}/original/{name}".format(
        id=instance.pk, name=filename)


class Cert(BasePositionModel):
    TYPES = (  # deprecated
        ('medical', 'Medical'),
        ('cpr', 'CPR'),
        ('ham', 'Ham'),
        ('tracking', 'Tracking'),
        ('avalanche', 'Avalanche'),
        ('rigging', 'Rigging'),
        ('ics', 'ICS'),
        ('overhead', 'Overhead'),
        ('driver', 'SO Driver'),
        ('background', 'SO Background'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255, null=True, blank=True)  # deprecated
    subtype = models.ForeignKey(CertSubType, on_delete=models.SET_NULL, null=True)
    earned_on = models.DateField(blank=True, null=True)
    expires_on = models.DateField(blank=True, null=True)
    description = models.CharField(max_length=255, blank=True)
    comment = models.CharField(max_length=255, blank=True, null=True)
    link = models.CharField(max_length=255, blank=True, null=True)
    # The following 'cert_' fields all refer to the cert_file.
    cert_file = models.FileField(upload_to=cert_upload_path_handler,
                                 max_length=255, blank=True, null=True)
    cert_name = models.CharField(max_length=255, blank=True, null=True)  # original file name
    cert_content_type = models.CharField(max_length=255, blank=True, null=True)
    cert_size = models.IntegerField(blank=True, null=True)
    ninety_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    thirty_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    expired_notice_sent_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # cleanup possible bad values from front end
        if self.link == 'None':
            self.link = None
        if self.comment == 'None':
            self.comment = None

        if self.pk is None:
            saved_file = self.cert_file
            self.cert_file = None
            super(Cert, self).save(*args, **kwargs)
            self.cert_file = saved_file
            super(Cert, self).save()
        else:
            super(Cert, self).save(*args, **kwargs)

    def __str__(self):
        if self.description is None:
            if self.subtype:
                return str(self.subtype)
            return ""
        return self.description

    @property
    def subtype_name(self):
        return self.subtype.name or ''

    @property
    def type_name(self):
        return self.subtype.type.name or ''

    @property
    def is_expired(self):
        # We will allow certs expiring today, thus < not <=
        return ((self.expires_on is not None) and
                (self.expires_on < timezone.now().date()))

    @property
    def color(self):
        exp = self.expires_on
        now = timezone.now().date()
        if not exp:
            return "white"
        if exp < now:
            return "red"
        if exp < now + timedelta(days=30):
            return "orange"
        if exp < now + timedelta(days=90):
            return "yellow"
        return "limegreen"

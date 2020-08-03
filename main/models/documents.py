# Google Drive Documents
#
# Any drive-specific code should live in lib.gdrive.

from django.db import models
from main.lib import gdrive
from .base import BaseModel, BasePositionMixin
from .member import DoAvailable

import logging
logger = logging.getLogger(__name__)

DOCUMENT_TYPES = (
    ('AAR', 'After Action Report'),
    ('AHC', 'AHC Log'),
    ('DO', 'DO Log'),
    ('L', 'Logistics / Carpool Spreadsheet'),
    ('TP', 'Training Plan'),
)


class BaseDocument(BaseModel):
    fileId = models.CharField(max_length=255, blank=True) # ID to look up document
    type = models.CharField(choices=DOCUMENT_TYPES, max_length=255, blank=True)
    class Meta:
        abstract = True

    def url(self):
        return 'https://docs.google.com/document/d/{}/edit'.format(self.fileId)


class DocumentTemplate(BasePositionMixin, BaseDocument):
    enabled = models.BooleanField(default=True)
    destinationId = models.CharField(max_length=255, blank=True)

    @classmethod
    def for_type(cls, type):
        result = cls.objects.filter(type=type, enabled=True)
        if result.count() == 0:  # allow more than 1, ordered by position
            logger.error('Expected 1 enabled template for {}, got {}: {}'.format(
                type, result.count(), result))
            return None
        else:
            return result.first()


class DoLog(BaseDocument):
    year = models.IntegerField()
    quarter = models.IntegerField()
    week = models.IntegerField()
    TYPE = 'DO'

    def add_writer(self, member):
        self.add_writer_emails(member.pagable_email_addresses())

    def add_writer_emails(self, emails):
        drive = gdrive.GoogleDrive()
        for email in emails:
            drive.add_writer(self.fileId, email)

    def date_range(self):
        return '{:%Y-%m-%d} - {:%Y-%m-%d}'.format(
            DoAvailable.shift_start(self.year, self.quarter, self.week),
            DoAvailable.shift_end(self.year, self.quarter, self.week))

    @classmethod
    def current_do_log(cls):
        """Returns the current DO log. If it somehow doesn't exist yet, create it."""
        return cls._get_or_create_do_log(DoAvailable.current_shift_dict())

    @classmethod
    def maybe_next_do_log(cls):
        """If it is time, create the next DO log."""
        do_log = cls.next_do_log()
        if do_log is None and DoAvailable.is_transition_period():
            logger.info('Creating next DO Log.')
            shift = DoAvailable.next_shift_dict()
            do = DoAvailable.scheduled_do(**shift)
            if do is None:
                logger.error('No next DO to transition to.')
                return None
            cls.current_do_log().add_writer(do)
            return cls._get_or_create_do_log(shift)
        return do_log

    @classmethod
    def next_do_log(cls):
        """Returns next log if it is already created or None if not."""
        return cls.objects.filter(**DoAvailable.next_shift_dict()).first()

    @classmethod
    def _get_or_create_do_log(cls, shift):
        template = DocumentTemplate.for_type(cls.TYPE)
        if template is None:
            logger.error('No DO log template')
            return None
        do = DoAvailable.scheduled_do(**shift)
        if do is None:  # Do check here so we don't create a bad version.
            return None
        obj, created = cls.objects.get_or_create(
            **shift,
            defaults={'type': cls.TYPE}
        )
        if created:
            drive = gdrive.GoogleDrive()
            title = 'BAMRU DO Log {} DO {}'.format(
                obj.date_range(), do.full_name)
            obj.fileId = drive.file_copy(
                template.fileId, template.destinationId, title)
            obj.save()
            obj.add_writer(do)
        return obj

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
    TYPE = None
    fileId = models.CharField(max_length=255, blank=True) # ID to look up document
    class Meta:
        abstract = True

    def url(self):
        return 'https://docs.google.com/document/d/{}/edit'.format(self.fileId)

    def add_writers(self, members):
        [self.add_writer(member) for member in members]

    def add_writer(self, member):
        self.add_writer_emails(member.pagable_email_addresses())

    def add_writer_emails(self, emails):
        drive = gdrive.GoogleDrive()
        for email in emails:
            drive.add_writer(self.fileId, email)

    @classmethod
    def _template(cls):
        return DocumentTemplate.for_type(cls.TYPE)

    def _copy(self, title):
        """Create from template. You must call save() after this function."""
        template = self._template()
        if template is None:
            logger.error('No {} template'.format(self.TYPE))
            return
        drive = gdrive.GoogleDrive()
        self.fileId = drive.file_copy(
            template.fileId, template.destinationId, title)
        # Does NOT call save() because this is usually used within save()


class DocumentTemplate(BasePositionMixin, BaseDocument):
    type = models.CharField(choices=DOCUMENT_TYPES, max_length=255, blank=True)
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


class Aar(BaseDocument):
    TYPE = 'AAR'
    event = models.OneToOneField(
        'Event',
        on_delete=models.CASCADE,
        related_name='aar',
    )

    def save(self, *args, **kwargs):
        if not self.pk:
            title = 'BAMRU AAR {}'.format(self.event.title)
            self._copy(title)
        if self.fileId:
            super(Aar, self).save(*args, **kwargs)
        else:
            logger.error('Skipping Aar.save due to missing fileId.')


class AhcLog(BaseDocument):
    TYPE = 'AHC'
    event = models.OneToOneField(
        'Event',
        on_delete=models.CASCADE,
        related_name='ahc_log',
    )

    def save(self, *args, **kwargs):
        if not self.pk:
            title = 'BAMRU AHC Log {}'.format(self.event.title)
            self._copy(title)
        if self.fileId:
            super(AhcLog, self).save(*args, **kwargs)
        else:
            logger.error('Skipping AhcLog.save due to missing fileId.')


class LogisticsSpreadsheet(BaseDocument):
    TYPE = 'L'
    event = models.OneToOneField(
        'Event',
        on_delete=models.CASCADE,
        related_name='logistics_spreadsheet',
    )

    def save(self, *args, **kwargs):
        if not self.pk:
            title = 'Logistics for {}'.format(self.event.title)
            self._copy(title)
        if self.fileId:
            super(LogisticsSpreadsheet, self).save(*args, **kwargs)
        else:
            logger.error('Skipping L.save due to missing fileId.')


class DoLog(BaseDocument):
    year = models.IntegerField()
    quarter = models.IntegerField()
    week = models.IntegerField()
    TYPE = 'DO'
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['year', 'quarter', 'week'], name='unique_do_log')
        ]

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
        if cls._template() is None:
            logger.error('No DO log template')
            return None
        do = DoAvailable.scheduled_do(**shift)
        if do is None:  # Do check here so we don't create a bad version.
            return None
        obj, created = cls.objects.get_or_create(**shift)
        if created:
            title = 'BAMRU DO Log {} DO {}'.format(
                obj.date_range(), do.full_name)
            self._copy(title)
            obj.save()
            obj.add_writer(do)
        return obj

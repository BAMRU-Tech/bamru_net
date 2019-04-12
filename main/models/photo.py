from django.db import models
from django.utils import timezone

from .base import BasePositionModel
from .member import Member

from datetime import date, datetime, timedelta

def file_upload_path_handler(instance, filename):
    return "images/{id}/original/{name}".format(
        id=instance.pk, name=filename)

class PhotoFile(BasePositionModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    file = models.ImageField(upload_to=file_upload_path_handler,
                             max_length=255, null=True)

    @property
    def size(self):
        return self.file.size

    @property
    def name(self):
        return self.file.name.split('/')[-1]

    def save(self, *args, **kwargs):
        if self.pk is None:
            saved_file = self.file
            self.file = None
            super(PhotoFile, self).save(*args, **kwargs)
            self.file = saved_file
            super(PhotoFile, self).save()
        else:
            super(PhotoFile, self).save(*args, **kwargs)

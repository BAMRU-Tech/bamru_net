from django.db import models
from django.utils import timezone

from .base import BaseModel
from .member import Member

from datetime import date, datetime, timedelta

def file_upload_path_handler(instance, filename):
    return "data/{id}/original/{name}".format(
        id=instance.pk, name=filename)

class DataFile(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    file = models.FileField(upload_to=file_upload_path_handler,
                            max_length=255, null=True)
    name = models.CharField(max_length=255)  # original file name
    extension = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size = models.IntegerField()
    caption = models.CharField(max_length=255, blank=True, null=True)
    download_count = models.IntegerField(default=0)
    published = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.pk is None:
            saved_file = self.file
            self.file = None
            super(DataFile, self).save(*args, **kwargs)
            self.file = saved_file
            super(DataFile, self).save()
        else:
            super(DataFile, self).save(*args, **kwargs)

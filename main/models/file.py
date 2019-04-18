from django.db import models
from django.utils import timezone

from .base import BaseModel, BasePositionMixin
from .member import Member

from datetime import date, datetime, timedelta

def file_upload_path_handler(instance, filename):
    return instance.upload_path(filename)


class BaseFileModel(BaseModel):
    file = models.FileField(upload_to=file_upload_path_handler,
                            max_length=255, null=True)
    name = models.CharField(max_length=255)  # original file name
    extension = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size = models.IntegerField()
    
    class Meta(BaseModel.Meta):
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is None:
            saved_file = self.file
            self.file = None
            super(BaseFileModel, self).save(*args, **kwargs)
            self.file = saved_file
            super(BaseFileModel, self).save()
        else:
            super(BaseFileModel, self).save(*args, **kwargs)


class DataFile(BaseFileModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    caption = models.CharField(max_length=255, blank=True, null=True)
    download_count = models.IntegerField(default=0)
    published = models.BooleanField(default=False)

    def upload_path(self, filename):
        return "data/{id}/original/{name}".format(
            id=self.pk, name=filename)

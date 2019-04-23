from django.db import models
from django.utils import timezone
from imagekit.models import ImageSpecField
from imagekit.processors import SmartResize, ResizeToFill, ResizeToFit

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


class MemberPhoto(BasePositionMixin, BaseFileModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    file = models.ImageField(upload_to=file_upload_path_handler,
                             max_length=255)
    thumbnail = ImageSpecField(source='file',
                               processors=[SmartResize(100, 100)],
                               format='JPEG',
                               options={'quality': 60})
    medium = ImageSpecField(source='file',
                            processors=[ResizeToFit(250, 250)],
                            format='JPEG',
                            options={'quality': 75})
    gallery_thumb = ImageSpecField(source='file',
                               processors=[SmartResize(50, 50)],
                               format='JPEG',
                               options={'quality': 60})

    def upload_path(self, filename):
        return "images/{id}/original/{name}".format(
            id=self.pk, name=filename)

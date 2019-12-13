#
#           Base Model
#
from django.conf import settings
from django.db import models

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

    @property
    def created_order(self):
        return self.created_at.timestamp()


class BasePositionMixin(models.Model):
    """Common handling for user-sorted items."""
    position = models.IntegerField(default=1, null=True) #TODO: old data has nulls
    class Meta:
        abstract = True
        ordering = ['position',]


class BasePositionModel(BasePositionMixin, BaseModel):
    class Meta(BasePositionMixin.Meta):
        abstract = True


class Configuration(BaseModel):
    key = models.CharField(max_length=255, unique=True)
    value = models.CharField(max_length=255)

    def __str__(self):
        return '{}: {}'.format(self.key, self.value)

    @classmethod
    def _format_key(cls, key):
        return '{}_{}'.format(key, settings.HOSTNAME)

    @classmethod
    def set_host_key(cls, key, value):
        return cls.objects.update_or_create(
            key=cls._format_key(key),
            defaults={'value': value})

    @classmethod
    def get_host_key_object(cls, key):
        key = '{}_{}'.format(key, settings.HOSTNAME)
        return cls.objects.filter(key=key).first()

    @classmethod
    def get_host_key(cls, key):
        object = cls.get_host_key_object(key)
        if object:
            return object.value
        else:
            return None

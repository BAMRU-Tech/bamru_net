#
#           Base Model
#
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

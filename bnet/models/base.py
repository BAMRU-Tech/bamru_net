#
#           Base Model
#
from django.db import models

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
        app_label = 'bnet'


class BasePositionModel(BaseModel):
    """Common handling for user-sorted items."""
    position = models.IntegerField(default=1)
    class Meta:
        abstract = True
        ordering = ['position',]

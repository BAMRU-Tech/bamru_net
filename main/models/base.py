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


class BasePositionModel(BaseModel):
    """Common handling for user-sorted items."""
    position = models.IntegerField(default=1, null=True) #TODO: old data has nulls
    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ['position',]

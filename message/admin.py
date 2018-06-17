from django.contrib import admin
from .models import *

class InlineDefaults(admin.TabularInline):
    extra = 0
    min_num = 0

class DistributionInline(InlineDefaults):
    model = Distribution

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('author', 'text', 'created_at', 'format', 'period_format', )
    inlines = [
        DistributionInline,
        ]

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from simple_history.admin import SimpleHistoryAdmin
from .models import *

# Register your models here.

class InlineDefaults(admin.TabularInline):
    extra = 0
    min_num = 0

class AddressInline(InlineDefaults):
    model = Address

class EmailInline(InlineDefaults):
    model = Email

class PhoneInline(InlineDefaults):
    model = Phone

class EmergencyContactInline(InlineDefaults):
    model = EmergencyContact

class RoleInline(InlineDefaults):
    model = Role

class OtherInfoInline(InlineDefaults):
    model = OtherInfo

class CertInline(InlineDefaults):
    model=Cert

class MemberUserAdmin(UserAdmin, SimpleHistoryAdmin):
    """Override broken defaults from UserAdmin"""
    fieldsets = None
    search_fields = []
    history_list_display = ["status"]

@admin.register(Member)
class MemberAdmin(MemberUserAdmin):
    list_display = ('last_name', 'first_name', 'status')
    list_filter = ('status', 'is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ['last_name', 'first_name', 'username',]
    inlines = [
        AddressInline,
        EmailInline,
        PhoneInline,
        EmergencyContactInline,
        RoleInline,
        OtherInfoInline,
        CertInline,
        ]


@admin.register(MemberStatusType)
class MemberStatusTypeAdmin(admin.ModelAdmin):
    list_display = ('short','long','position')


class ParticipantInline(InlineDefaults):
    model = Participant

class PeriodInline(InlineDefaults):
    model = Period

@admin.register(Event)
class EventAdmin(SimpleHistoryAdmin):
    list_display = ('title', 'type', 'start_at', 'finish_at',)
    inlines = [
        PeriodInline,
        ]

@admin.register(Period)
class PeriodAdmin(SimpleHistoryAdmin):
    list_display = ('__str__', 'event', 'position', 'start_at', 'finish_at',)
    inlines = [
        ParticipantInline,
        ]

@admin.register(DoAvailable)
class DoAvailableAdmin(admin.ModelAdmin):
    search_fields = ['member__last_name', 'member__first_name', 'member__username']


class DistributionInline(InlineDefaults):
    model = Distribution


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('author', 'text', 'created_at',
                    'format', 'period_format', )
    inlines = [
        DistributionInline,
    ]


@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')

@admin.register(DataFile)
class DataFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'member')
    search_fields = ['name',]

@admin.register(MemberPhoto)
class MemberPhotoAdmin(admin.ModelAdmin):
    list_display = ('name', 'file', 'created_at', 'member')
    search_fields = ['member',]

# Documents
@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('type', 'enabled', 'url')
    readonly_fields = ('url', )

@admin.register(DoLog)
class DoLogAdmin(admin.ModelAdmin):
    list_display = ('year', 'quarter', 'week', 'url',)
    readonly_fields = ('url', )

@admin.register(Aar)
class AarAdmin(admin.ModelAdmin):
    list_display = ('event', 'url',)
    readonly_fields = ('url', )

@admin.register(AhcLog)
class AhcLogAdmin(admin.ModelAdmin):
    list_display = ('event', 'url',)
    readonly_fields = ('url', )

@admin.register(LogisticsSpreadsheet)
class LogisticsSpreadsheetAdmin(admin.ModelAdmin):
    list_display = ('event', 'url',)
    readonly_fields = ('url', )

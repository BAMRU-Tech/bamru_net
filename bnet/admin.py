from django.contrib import admin

from .models import *

# Register your models here.


class InlineDefaults(admin.TabularInline):
    extra = 0
    min_num = 1

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


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('last_name', 'first_name', 'typ')
    list_filter = ('typ', )
    inlines = [
        AddressInline,
        EmailInline,
        PhoneInline,
        EmergencyContactInline,
        RoleInline,
        OtherInfoInline,
        ]


class DistributionInline(InlineDefaults):
    model = Distribution

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('author', 'text', 'created_at', 'format', 'period_format', )
    inlines = [
        DistributionInline,
        ]

class ParticipantInline(InlineDefaults):
    model = Participant

class PeriodInline(InlineDefaults):
    model = Period

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'typ', 'start', 'finish',)
    inlines = [
        PeriodInline,
        ]

@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'event', 'position', 'start', 'finish',)
    inlines = [
        ParticipantInline,
        ]

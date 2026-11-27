# Preferences using django-dynamic-preferences

from django import forms
from django.core.exceptions import ValidationError
from dynamic_preferences import types
from dynamic_preferences.preferences import Section
from dynamic_preferences.registries import global_preferences_registry

from main.lib.lat_lon import area_edges

general = Section('general')
google = Section('google')

###############################################################################
# General section

@global_preferences_registry.register
class CertNotice(types.BooleanPreference):
    section = general
    name = 'cert_notice'
    verbose_name = 'Enable sending cert expiration notices'
    default = False

@global_preferences_registry.register
class WikiUrl(types.StringPreference):
    section = general
    name = 'wiki_url'
    default = 'https://wiki.bamru.net/mediawiki/index.php?title=Special:UserLogin&returnto=Main+Page'

@global_preferences_registry.register
class EsbSpreadsheetUrl(types.StringPreference):
    section = general
    name = 'esb_spreadsheet_url'
    verbose_name = 'ESB spreadsheet opened after copying ESB details on an event'
    default = ''

@global_preferences_registry.register
class EventArea(types.StringPreference):
    section = general
    name = 'event_area'
    verbose_name = 'Event Lat/Lon area: south, north, west and east edges'
    help_text = ('The box the team usually works in, as four numbers in decimal degrees, in this order: '
                 'south edge, north edge, west edge, east edge. An event point inside the box saves with '
                 'no warning. A point outside it gets a warning on the event form, asking the member to '
                 'check it, and still saves. West and east are negative in the US. The default covers '
                 'California, Nevada and Oregon.')
    default = '32.4, 46.4, -124.8, -114.0'
    required = True
    widget = forms.TextInput(attrs={'size': 30})

    def validate(self, value):
        try:
            area_edges(value)
        except ValueError as problem:
            raise ValidationError(str(problem))

@global_preferences_registry.register
class EventCountyBorderMiles(types.FloatPreference):
    section = general
    name = 'event_county_border_miles'
    verbose_name = 'Event county: miles from a county line to name the counties across it'
    help_text = ('The event page names the county an event\'s Lat/Lon is in. Within this many miles of a '
                 'county line, it also names the counties across it, such as "Placer, bordering Nevada". '
                 '0 names only the county the point is in.')
    default = 3.0
    required = True

    def validate(self, value):
        if value < 0:
            raise ValidationError('Enter 0 or more miles.')

###############################################################################
# Google section

@global_preferences_registry.register
class GoogleCredentials(types.LongStringPreference):
    section = google
    name = 'credentials'
    verbose_name = 'JSON credentials for service account'
    default = ''

@global_preferences_registry.register
class GoogleUser(types.StringPreference):
    section = google
    name = 'user'
    verbose_name = 'Delegated user on GSuite domain'
    default = ''

@global_preferences_registry.register
class DoGroup(types.StringPreference):
    section = google
    name = 'do_group'
    verbose_name = 'Google group to hold DO/AHCs'
    default = ''

@global_preferences_registry.register
class CalendarIdPublic(types.StringPreference):
    section = google
    name = 'calendar_id_public'
    verbose_name = 'Google calendar ID - public'
    default = ''

@global_preferences_registry.register
class CalendarIdPrivate(types.StringPreference):
    section = google
    name = 'calendar_id_private'
    verbose_name = 'Google calendar ID - private'
    default = ''

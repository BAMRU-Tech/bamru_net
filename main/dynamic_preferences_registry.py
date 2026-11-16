# Preferences using django-dynamic-preferences

from dynamic_preferences import types
from dynamic_preferences.preferences import Section
from dynamic_preferences.registries import global_preferences_registry

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

# The area the team's events usually fall in: California, Nevada and Oregon. A new point
# outside it is questioned on the event form before it is saved.

@global_preferences_registry.register
class EventAreaSouth(types.FloatPreference):
    section = general
    name = 'event_area_south'
    verbose_name = "Southern edge of the team's usual event area (latitude)"
    default = 32.4

@global_preferences_registry.register
class EventAreaNorth(types.FloatPreference):
    section = general
    name = 'event_area_north'
    verbose_name = "Northern edge of the team's usual event area (latitude)"
    default = 46.4

@global_preferences_registry.register
class EventAreaWest(types.FloatPreference):
    section = general
    name = 'event_area_west'
    verbose_name = "Western edge of the team's usual event area (longitude)"
    default = -124.8

@global_preferences_registry.register
class EventAreaEast(types.FloatPreference):
    section = general
    name = 'event_area_east'
    verbose_name = "Eastern edge of the team's usual event area (longitude)"
    default = -114.0

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

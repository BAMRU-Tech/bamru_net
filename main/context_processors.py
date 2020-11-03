from django.conf import settings
from dynamic_preferences.registries import global_preferences_registry

def dsn(request):
    global_preferences = global_preferences_registry.manager()
    return {
        'JAVASCRIPT_DSN': settings.JAVASCRIPT_DSN,
        'RELEASE': settings.RELEASE,
        'WIKI_URL': global_preferences['general__wiki_url']
    }

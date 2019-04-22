from django.conf import settings

def dsn(request):
    return {
        'ICON_SET': settings.ICON_SET,
        'JAVASCRIPT_DSN': settings.JAVASCRIPT_DSN,
        'RELEASE': settings.RELEASE,
        'WIKI_URL': settings.WIKI_URL,
        'isEditor': request.user.is_authenticated and request.user.is_editor,
    }

from django.conf import settings

def dsn(request):
    return {
        'JAVASCRIPT_DSN': settings.JAVASCRIPT_DSN,
        'RELEASE': settings.RELEASE,
        'WIKI_URL': settings.WIKI_URL,
        'isEditor': (
            request.user.is_authenticated and
            (request.user.is_staff or
             request.user.role_set.filter(role='SEC').exists() or
             request.user.role_set.filter(role='RO').exists())
        )
    }

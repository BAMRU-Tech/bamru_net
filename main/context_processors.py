from django.conf import settings

def dsn(request):
    return {'JAVASCRIPT_DSN': settings.JAVASCRIPT_DSN}

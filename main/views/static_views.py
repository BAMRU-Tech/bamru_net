from django.conf import settings

from django.shortcuts import redirect

def favicon_view(request):
    url = '/static/favicon/{}/favicon.ico'.format(settings.ICON_SET)
    return redirect(url)

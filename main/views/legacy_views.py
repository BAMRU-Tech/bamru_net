from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.views import View

import os
import subprocess


class LegacyWikiSsoView(LoginRequiredMixin, View):
    def wiki_username(self, user):
        return user.full_name.replace(' ', '.')

    def get(self, request):
        path = request.GET.get('wiki_path', '/')
        path = path.split('?')[0]
        wiki_username = self.wiki_username(request.user)
        auth_file = os.path.join(settings.WIKI_AUTH_DIR, wiki_username)
        with open('/dev/null', 'r') as devnull:
            subprocess.check_call(['/usr/bin/env'], stdin=devnull, env={})
            subprocess.check_call([
                '/usr/bin/ssh',
                '-o', 'BatchMode=yes',  # fail rather than hanging at a prompt
                '-o', 'StrictHostKeyChecking=no',
                '-i', settings.WIKI_SSH_KEY,
                settings.WIKI_SSH_DEST,
                'touch', auth_file], stdin=devnull, env={})
        return HttpResponseRedirect('{}{}?username={}'.format(settings.WIKI_BASE_URL, path, wiki_username))

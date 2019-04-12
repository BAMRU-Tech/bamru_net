from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, Http404
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView

from main.models import PhotoFile

import logging
logger = logging.getLogger(__name__)

@login_required
def download_photo_file_by_id_view(request, id, name):
    f = get_object_or_404(PhotoFile, id=id)
    response = HttpResponse()
    response['Content-Type'] = ''  # Let nginx infer it
    response['X-Accel-Redirect'] = f.file.url
    logger.info(response)
    return response

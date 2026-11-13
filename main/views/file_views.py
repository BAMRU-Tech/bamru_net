from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, Http404
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView

from main.models import DataFile, MemberPhoto

import logging
logger = logging.getLogger(__name__)

class BaseFileFormView(LoginRequiredMixin, CreateView):
    template_name = 'base_form.html'
    model = None  # Must be filled in by sub-class
    fields = ('file', )

    def get_form(self, form_class=None):
        form = super(BaseFileFormView, self).get_form(form_class)
        form.instance.member = self.request.user
        if 'file' in self.request.FILES:
            f = self.request.FILES['file']
            form.instance.name = f.name
            form.instance.size = f.size
            form.instance.content_type = f.content_type
            if '.' in f.name:
                form.instance.extension = f.name.split('.')[-1]
        return form


class DataFileFormView(BaseFileFormView):
    model = DataFile
    fields = ('file', 'caption', )
    def get_success_url(self, *args, **kwargs):
        return reverse('file_list')


class FileListView(LoginRequiredMixin, generic.ListView):
    template_name = 'file_list.html'
    context_object_name = 'file_list'

    def get_queryset(self):
        return DataFile.objects.order_by('name').select_related('member')


def download_file_helper(url, filename='', download=False):
    """Set download to make browsers download instead of displaying inline."""
    if not settings.ENABLE_ACCEL_REDIRECT:
        return redirect(url)
    response = HttpResponse()
    response['Content-Type'] = ''  # Let nginx infer it
    response['X-Accel-Redirect'] = url
    if download:
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(
            filename)
    return response

def download_data_file_helper(data_file, increment=True):
    if increment:
        data_file.download_count += 1
        data_file.save()
    return download_file_helper(data_file.file.url, data_file.name, False)

@login_required
def download_data_file_by_id_view(request, id):
    f = get_object_or_404(DataFile, id=id)
    return download_data_file_helper(f)

@login_required
def download_data_file_by_name_view(request, name):
    files = get_list_or_404(DataFile, name=name)
    f = files[0]  # TODO: Do we prefer the oldest or most recent?
    return download_data_file_helper(f)

@login_required
def member_photo_by_id_view(request, id, format):
    photos = get_list_or_404(MemberPhoto, id=id)
    if format == "original":
        f = photos[0].file
    elif format == "thumbnail":
        f = photos[0].thumbnail
    elif format == "medium":
        f = photos[0].medium
    elif format == "gallery_thumb":
        f = photos[0].gallery_thumb
    else:
        raise Http404()
    return download_file_helper(f.url, photos[0].name)

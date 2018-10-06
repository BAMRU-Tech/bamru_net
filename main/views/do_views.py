
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelformset_factory
from django.views import generic

from main.models import DoAvailable

from collections import defaultdict

class DoAbstractView(LoginRequiredMixin):
    def get_params(self):
        year = self.request.GET.get('year', '')
        if year.isnumeric():
            self.year = int(year)
        else:
            self.year = DoAvailable.current_year()
        quarter = self.request.GET.get('quarter', '')
        if quarter.isnumeric():
            self.quarter = int(quarter)
        else:
            self.quarter = DoAvailable.current_quarter()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.get_params()

        context['year'] = self.year
        context['quarter'] = self.quarter
        context['weeks'] = DoAvailable.weeks(self.year, self.quarter)

        query = '?year={}&quarter={}'
        context['query_this'] = query.format(self.year, self.quarter)
        if self.quarter == 1:
            context['query_prev'] = query.format(self.year - 1, 4)
        else:
            context['query_prev'] = query.format(self.year, self.quarter - 1)
        if self.quarter == 4:
            context['query_next'] = query.format(self.year + 1, 1)
        else:
            context['query_next'] = query.format(self.year, self.quarter + 1)
        return context


class DoListView(DoAbstractView, generic.ListView):
    template_name = 'do_list.html'
    context_object_name = 'do_list'

    def get_queryset(self):
        super().get_params()
        qs = DoAvailable.objects.filter(year=self.year,
                                        quarter=self.quarter,
                                        assigned=True)
        return qs.select_related('member').order_by('week')


class DoPlanView(DoAbstractView, generic.base.TemplateView):
    template_name = 'do_plan.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        qs = DoAvailable.objects.filter(
            year=self.year, quarter=self.quarter
        ).select_related('member')

        def default_value():
            return {
                'assigned': False,
                'weeks': [None for x in context['weeks']],
            }
        week_info = [{'assigned': False, 'week': w} for w in context['weeks']]
        members = defaultdict(default_value)
        for x in qs:
            members[x.member]['weeks'][x.week-1] = x
            if x.assigned:
                members[x.member]['assigned'] = True
                week_info[x.week-1]['assigned'] = True
        context['members'] = members.items()
        context['week_info'] = week_info
        return context


class DoEditView(DoAbstractView, generic.base.TemplateView):
    template_name = 'member_do_list.html'

    def post(self, *args, **kwargs):
        return self.get(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        DoFormSet = modelformset_factory(
            DoAvailable,
            fields=['week', 'available', 'comment',],
            extra=0,
        )
        initial= [{
            'week': w,
        } for w in DoAvailable.weeks(self.year, self.quarter)]

        qs = DoAvailable.objects.filter(member=self.request.user,
                                        year=self.year,
                                        quarter=self.quarter)

        for do in qs:
            initial[do.week-1]['available'] = do.available
            initial[do.week-1]['comment'] = do.comment

        if self.request.method == 'POST':
            formset = DoFormSet(self.request.POST, initial=initial)
            if formset.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    do, created = DoAvailable.objects.get_or_create(
                        member=self.request.user,
                        year=self.year,
                        quarter=self.quarter,
                        week=instance.week)
                    do.available = instance.available
                    do.comment = instance.comment
                    do.save()
        else:
            DoFormSet.extra = DoAvailable.num_weeks_in_quarter(
                self.year, self.quarter)
            formset = DoFormSet(
                queryset=DoAvailable.objects.none(),
                initial=initial)
        context['formset'] = formset
        return context

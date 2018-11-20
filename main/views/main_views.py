from main.models import Member

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.base import TemplateView
from django_datatables_view.base_datatable_view import BaseDatatableView


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = 'index.html'


class OrderListJson(BaseDatatableView):
    # The model we're going to show
    model = Member

    # define the columns that will be returned
    columns = ['last_name', 'status', 'role', 'phone', 'email']
        
    # define column names that will be used in sorting
    # order is important and should be same as order of columns
    # displayed by datatables. For non sortable columns use empty
    # value like ''
    order_columns = ['last_name', 'status', 'role', '', '']

    # set max limit of records returned, this is used to protect our site
    # if someone tries to attack our site and make it return huge amount of data
    max_display_length = 500

    def render_column(self, row, column):
        # We want to render user as a custom column
        return super(OrderListJson, self).render_column(row, column)

    def filter_queryset(self, qs):
        # use parameters passed in GET request to filter queryset

        # simple example:
        search = self.request.GET.get(u'search[value]', None)
        if search:
            qs = qs.filter(name__istartswith=search)

        # more advanced example using extra parameters
        filter_customer = self.request.GET.get(u'customer', None)

        if filter_customer:
            customer_parts = filter_customer.split(' ')
            qs_params = None
            for part in customer_parts:
                q = Q(customer_firstname__istartswith=part)|Q(customer_lastname__istartswith=part)
                qs_params = qs_params | q if qs_params else q
            qs = qs.filter(qs_params)
        return qs

from datetime import timedelta

from django.conf import settings
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q, F
from django.forms import ModelChoiceField
from django.utils import timezone
from django_filters import FilterSet, filters, OrderingFilter

from helpdesk.models import Ticket, Queue
from helpdesk.utils import ExtendedOrderingFilter

User = get_user_model()


class TicketsFilter(FilterSet):
    no_assigned = filters.BooleanFilter(field_name='assigned_to', method='no_assigned_filter')
    assigned_to = filters.ModelChoiceFilter(
        empty_label='', required=False, queryset=User.objects.filter(is_staff=True, is_active=True).all(),
        widget=forms.Select(attrs={
            'data-placeholder': 'Filter by Owner',
            'class': 'form-control chosen-select-deselect'}))

    queue = filters.ModelMultipleChoiceFilter(
        required=False, queryset=Queue.objects.all(),
        widget=forms.SelectMultiple(attrs={
            'data-placeholder': 'Filter by Queue',
            'class': 'form-control chosen-select'}))

    status = filters.MultipleChoiceFilter(
        required=False, choices=Ticket.STATUS_CHOICES,
        widget=forms.SelectMultiple(attrs={
            'data-placeholder': 'Filter by Status',
            'class': 'form-control chosen-select'}))
    priority = filters.MultipleChoiceFilter(
        required=False, choices=Ticket.PRIORITY_CHOICES,
        widget=forms.SelectMultiple(attrs={
            'data-placeholder': 'Filter by Priority',
            'class': 'form-control chosen-select'}))
    created_min = filters.DateFilter(field_name='created', lookup_expr='gte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'From Date',
                                         'class': 'form-control datepicker-widget'}))
    created_max = filters.DateFilter(field_name='created', lookup_expr='lte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'To Date',
                                         'class': 'form-control datepicker-widget'}))
    keywords = filters.CharFilter(method='keywords_filter',
                                  widget=forms.TextInput(attrs={
                                      'placeholder': 'Search by Keywords',
                                      'class': 'form-control'}))

    order_by = ExtendedOrderingFilter(
        fields=['id', 'queue', 'priority', 'assigned_to', 'status', 'title', 'description', 'created', 'due_date',
                'time_tracks', 'money_tracks', 'time_open', 'submitter_email'],
        ordering_map={
            'queue': 'queue__title',
            'assigned_to': ('assigned_to__first_name', 'assigned_to__last_name'),
            'status': ('status', 'modified_status'),
            'submitter_email': lambda desceding: F('submitter_email').desc(nulls_last=True) if desceding else F(
                'submitter_email').asc(nulls_last=True)
        }

    )

    def keywords_filter(self, queryset, name, value):
        filters = Q(title__icontains=value) | Q(description__icontains=value)
        if value.startswith('#') and value[1:].isdigit():
            filters = filters | Q(pk=int(value[1:]))

        return queryset.filter(filters)

    def no_assigned_filter(self, queryset, name, value):
        return queryset.filter(assigned_to__isnull=True)

    class Meta:
        model = Ticket
        fields = [
             'assigned_to', 'queue', 'status', 'priority', 'created_min', 'created_max', 'keywords', 'submitter_email',
        ]


class CustomDateReportFilter(FilterSet):
    DATE_RANGE_CHOICES = (
        ('today', 'Today'),
        ('yesterday', 'Yesterday'),
        ('this_week', 'This Week'),
        ('this_month', 'This Month'),
        ('this_year', 'This Year')
    )
    created_min = filters.DateFilter(field_name='created', lookup_expr='gte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'From Date',
                                         'class': 'form-control datepicker-widget'}))
    created_max = filters.DateFilter(field_name='created', lookup_expr='lte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'To Date',
                                         'class': 'form-control datepicker-widget'}))
    date_range = filters.ChoiceFilter(method='date_range_filter', choices=(DATE_RANGE_CHOICES))
    order_by = ExtendedOrderingFilter(
        fields=['id', 'queue', 'priority', 'assigned_to', 'title', 'created', 'due_date', 'time_tracks', 'money_tracks',
                'closed_at_null', 'closed_at'],
        ordering_map={
            'queue': 'queue__title',
            'assigned_to': ('assigned_to__first_name', 'assigned_to__last_name'),
            'status': ('status', 'modified_status')
        }

    )

    @classmethod
    def get_range_by_name(cls, value):
        today = timezone.now().date()
        start_date = end_date = None
        if value not in dict(cls.DATE_RANGE_CHOICES).keys():
            value = 'this_month'
        if value == 'today':
            start_date = end_date = today
        elif value == 'yesterday':
            start_date = end_date = today - timedelta(days=1)
        elif value == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
        elif value == 'this_month':
            start_date = today.replace(day=1)
            end_date = (start_date.replace(day=27) + timedelta(days=5)).replace(day=1) - timedelta(days=1)
        elif value == 'this_year':
            start_date = today.replace(day=1, month=1)
            end_date = start_date.replace(year=start_date.year + 1) - timedelta(days=1)
        return (start_date, end_date)

    def date_range_filter(self, queryset, name, value):
        start_date, end_date = self.get_range_by_name(value)
        if start_date:
            queryset = queryset.filter(created__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created__date__lte=end_date)
        return queryset

    def get_range_display(self):
        self.form.is_valid()
        filter_data = self.form.cleaned_data

        if filter_data.get('date_range'):
            date_range = self.get_range_by_name(filter_data['date_range'])
            return (dict(self.DATE_RANGE_CHOICES).get(filter_data['date_range']), date_range)
        return ('Custom', (filter_data['created_min'], filter_data['created_max']))

    class Meta:
        model = Ticket
        fields = ['created_min', 'created_max',]

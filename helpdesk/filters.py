from django.conf import settings
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms import ModelChoiceField
from django_filters import FilterSet, filters, OrderingFilter

from helpdesk.models import Ticket, Queue
from helpdesk.utils import ExtendedOrderingFilter

User = get_user_model()


class TicketsFilter(FilterSet):
    no_assigned = filters.BooleanFilter(name='assigned_to', method='no_assigned_filter')
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
    created_min = filters.DateFilter(name='created', lookup_expr='gte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'From Date',
                                         'class': 'form-control datepicker-widget'}))
    created_max = filters.DateFilter(name='created', lookup_expr='lte', required=False,
                                     widget=forms.DateInput(attrs={
                                         'placeholder': 'To Date',
                                         'class': 'form-control datepicker-widget'}))
    keywords = filters.CharFilter(method='keywords_filter',
                                  widget=forms.TextInput(attrs={
                                      'placeholder': 'Search by Keywords',
                                      'class': 'form-control'}))

    order_by = ExtendedOrderingFilter(
        fields=['id', 'queue', 'priority', 'assigned_to', 'status', 'title', 'description', 'created', 'due_date',
                'time_tracks', 'money_tracks', 'time_open'],
        ordering_map={
            'queue': 'queue__title',
            'assigned_to': ('assigned_to__first_name', 'assigned_to__last_name'),
            'status': ('status', 'modified_status')
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
             'assigned_to', 'queue', 'status', 'priority', 'created_min', 'created_max', 'keywords',
        ]



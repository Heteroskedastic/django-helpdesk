from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse, QueryDict
from django.core.urlresolvers import reverse
from django.utils import six
from django.utils.safestring import mark_safe
from django_filters import OrderingFilter
from django_filters.filters import EMPTY_VALUES

from helpdesk import settings as helpdesk_settings


class StaffLoginRequiredMixin(LoginRequiredMixin):
    def get_login_url(self):
        return reverse('helpdesk:login')

    def handle_no_authenticated(self):
        if self.request.is_ajax():
            return JsonResponse({'error': 'Not Authorized'}, status=401)
        return redirect_to_login(self.request.get_full_path(),
                                 self.get_login_url(),
                                 self.get_redirect_field_name())

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated():
            return self.handle_no_authenticated()
        if not request.user.is_staff:
            msg = 'Please enter the correct username and password for a superuser account!'
            messages.error(request, mark_safe(msg), extra_tags='danger')
            return self.handle_no_authenticated()
        return super(StaffLoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class ExtendedOrderingFilter(OrderingFilter):
    def __init__(self, *args, **kwargs):
        self.ordering_map = kwargs.pop('ordering_map', {})
        super(ExtendedOrderingFilter, self).__init__(*args, **kwargs)

    def get_ordering_value(self, param):
        descending = param.startswith('-')
        param = param[1:] if descending else param
        field_name = self.param_map.get(param, param)
        field_name = self.ordering_map.get(field_name, field_name)
        if isinstance(field_name, str):
            field_name = (field_name,)

        return [("-%s" % f if descending else f) for f in field_name]

    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        ordering = []
        for param in value:
            ordering.extend(list(self.get_ordering_value(param)))
        return qs.order_by(*ordering)


class BulkableActionMixin(object):
    pk_url_kwarg = 'pk'

    def get_bulk_ids(self):
        return [int(i) for i in self.kwargs.get(self.pk_url_kwarg).rstrip(',').split(',')]

    def get_queryset(self):
        ids = self.get_bulk_ids()
        qs = self.model.objects
        return qs.filter(id__in=ids)


def get_current_page_size(request):
    PAGINATION_DEFAULT_PAGINATION = helpdesk_settings.HELPDESK_PAGINATION_DEFAULT_PAGINATION
    PAGINATION_MAX_SIZE = helpdesk_settings.HELPDESK_PAGINATION_MAX_SIZE
    try:
        user_default_page_size = int(request.user.usersettings_helpdesk.settings.get('tickets_per_page')) or None
    except ValueError:
        user_default_page_size = None
    page_size = user_default_page_size or PAGINATION_DEFAULT_PAGINATION
    try:
        page_size = int(request.GET.get('page_size'))
    except (ValueError, TypeError):
        pass

    if page_size <= 0:
        page_size = PAGINATION_DEFAULT_PAGINATION
    return min(page_size, PAGINATION_MAX_SIZE)


def success_message(message, request):
    return messages.success(request, mark_safe(message))


def error_message(message, request):
    return messages.error(request, mark_safe(message), extra_tags='danger')


def info_message(message, request):
    return messages.info(request, mark_safe(message))


def warning_message(message, request):
    return messages.warning(request, mark_safe(message))


def send_form_errors(form, request):
    msgs = []
    for k, v in form.errors.items():
        msg = '' if k.startswith('__') else '{0}: '.format(k)
        msgs.append('<li>{0}{1}</li>'.format(msg, ', '.join(v)))

    if msgs:
        return error_message(''.join(msgs), request)


def to_bool(val):
    val = str(val).lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    return False


def to_query_dict(d):
    qdict = QueryDict('', mutable=True)
    for key, value in d.items():
        if not isinstance(value, list):
            value = [value]
        qdict.setlist(key, value)
    return qdict

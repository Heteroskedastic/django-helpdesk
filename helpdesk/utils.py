from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import F, Expression
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
        if callable(field_name):
            res = field_name(descending)
            if not isinstance(res, (tuple, list)):
                res = [res]
            return res
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


class ResolvedOuterRef(F):
    """
    An object that contains a reference to an outer query.

    In this case, the reference to the outer query has been resolved because
    the inner query has been used as a subquery.
    """
    def as_sql(self, *args, **kwargs):
        raise ValueError(
            'This queryset contains a reference to an outer query and may '
            'only be used in a subquery.'
        )

    def _prepare(self, output_field=None):
        return self


class OuterRef(F):
    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        if isinstance(self.name, self.__class__):
            return self.name
        return ResolvedOuterRef(self.name)
    def _prepare(self, output_field=None):
        return self


class Subquery(Expression):
    """
    An explicit subquery. It may contain OuterRef() references to the outer
    query which will be resolved when it is applied to that query.
    """
    template = '(%(subquery)s)'

    def __init__(self, queryset, output_field=None, **extra):
        self.queryset = queryset
        self.extra = extra
        if output_field is None and len(self.queryset.query.select) == 1:
            output_field = self.queryset.query.select[0].field
        super(Subquery, self).__init__(output_field)

    def copy(self):
        clone = super(Subquery, self).copy()
        clone.queryset = clone.queryset.all()
        return clone

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        clone = self.copy()
        clone.is_summary = summarize
        clone.queryset.query.bump_prefix(query)

        # Need to recursively resolve these.
        def resolve_all(child):
            if hasattr(child, 'children'):
                [resolve_all(_child) for _child in child.children]
            if hasattr(child, 'rhs'):
                child.rhs = resolve(child.rhs)

        def resolve(child):
            if hasattr(child, 'resolve_expression'):
                resolved = child.resolve_expression(
                    query=query, allow_joins=allow_joins, reuse=reuse,
                    summarize=summarize, for_save=for_save,
                )
                # Add table alias to the parent query's aliases to prevent
                # quoting.
                if hasattr(resolved, 'alias'):
                    clone.queryset.query.external_aliases.add(resolved.alias)
                return resolved
            return child

        resolve_all(clone.queryset.query.where)

        for key, value in clone.queryset.query.annotations.items():
            if isinstance(value, Subquery):
                clone.queryset.query.annotations[key] = resolve(value)

        return clone

    def get_source_expressions(self):
        return [
            x for x in [
                getattr(expr, 'lhs', None)
                for expr in self.queryset.query.where.children
            ] if x
        ]

    def relabeled_clone(self, change_map):
        clone = self.copy()
        clone.queryset.query = clone.queryset.query.relabeled_clone(change_map)
        clone.queryset.query.external_aliases.update(
            alias for alias in change_map.values()
            if alias not in clone.queryset.query.tables
        )
        return clone

    def as_sql(self, compiler, connection, template=None, **extra_context):
        connection.ops.check_expression_support(self)
        template_params = self.extra.copy()
        template_params.update(extra_context)
        template_params['subquery'], sql_params = self.queryset.query.get_compiler(connection=connection).as_sql()

        template = template or template_params.get('template', self.template)
        sql = template % template_params
        return sql, sql_params

    def _prepare(self, output_field):
        # This method will only be called if this instance is the "rhs" in an
        # expression: the wrapping () must be removed (as the expression that
        # contains this will provide them). SQLite evaluates ((subquery))
        # differently than the other databases.
        if self.template == '(%(subquery)s)':
            clone = self.copy()
            clone.template = '%(subquery)s'
            return clone
        return self

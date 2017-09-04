from collections import OrderedDict
from datetime import timedelta
from django.utils import timezone
from django.contrib.humanize.templatetags.humanize import naturaltime, intcomma
from helpdesk import settings
from django import template

from helpdesk.utils import get_current_page_size

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode
from django import template
from django.utils.translation import ngettext, ugettext as _
from django.utils.safestring import mark_safe


register = template.Library()

# noinspection PyAugmentAssignment
@register.filter
def humanize_duration(seconds):
    if isinstance(seconds, timedelta):
        seconds = int(seconds.total_seconds())
    if not seconds:
        return None
    s = m = h = d = ''
    if seconds >= 86400:
        days = seconds // 86400
        seconds = seconds % 86400
        d = ngettext("%d day", "%d days", days) % days
    if seconds >= 3600:
        hours = seconds // 3600
        seconds = seconds % 3600
        h = ngettext("%d hour", "%d hours", hours) % hours
    if seconds >= 60:
        minutes = seconds // 60
        seconds = seconds % 60
        m = ngettext("%d minute", "%d minutes", minutes) % minutes
    res = ', '.join([i for i in (d, h, m, s) if i])
    return res or _('a few seconds')

# noinspection PyAugmentAssignment
@register.filter()
def seconds_to_time(delta, format='short'):
    def plural(n):
        return n, abs(n) != 1 and "s" or ""

    if isinstance(delta, str):
        delta = int(delta)
    if not isinstance(delta, timedelta):
        delta = timedelta(seconds=delta)

    days = ''
    if delta.days:
        days = "%d day%s" % plural(delta.days)
        if format == 'short':
            return days
        days = days + ', '

    mm, ss = divmod(delta.seconds, 60)
    hh, mm = divmod(mm, 60)
    s = "%d:%02d:%02d" % (hh, mm, ss)
    if delta.days:
        s = '{}{}'.format(days, s)
    return s


@register.filter_function
def order_by(queryset, args):
    args = [x.strip() for x in args.split(',')]
    return queryset.order_by(*args)


@register.simple_tag(takes_context=True)
def sorting_link(context, text, value, field='order_by', direction=''):
    dict_ = context.request.GET.copy()
    icon = 'fa fa-fw '
    link_css = ''
    if field in dict_.keys():
        if dict_[field].startswith('-') and dict_[field].lstrip('-') == value:
            dict_[field] = value
            icon += 'fa-sort-desc'
            link_css += 'text-italic'
        elif dict_[field].lstrip('-') == value:
            dict_[field] = "-" + value
            icon += 'fa-sort-asc'
            link_css += 'text-italic'
        else:
            dict_[field] = direction + value
            icon += 'fa-sort gray2-color'
    else:
        dict_[field] = direction + value
        icon += 'fa-sort gray2-color'
    u = urlencode(OrderedDict(sorted(dict(dict_).items())), True)

    return mark_safe('<a href="?{0}" class="{1}">{2}<i class="{3}">'
                     '</i></a>'.format(u, link_css, text, icon))


@register.filter
def ticket_due_date_humanize(ticket):
    due = ticket.due_date
    if not due:
        return None
    if ticket.status in (ticket.RESOLVED_STATUS, ticket.CLOSED_STATUS, ticket.DUPLICATE_STATUS):
        return due.strftime('%b %d, %Y')
    replacements = {
        'year': 'yr', 'month': 'mo', 'week': 'wk', 'day': 'd', 'hour': 'h', 'minute': 'm', 'second': 's',
    }
    value = naturaltime(due).replace('from now', '').replace('ago', 'past due')
    for k, v in replacements.items():
        value = value.replace(k+'s', v).replace(k, v)

    return value


@register.filter
def ticket_due_date_css(ticket):
    due = ticket.due_date
    if not due:
        return ''

    if ticket.status in (ticket.RESOLVED_STATUS, ticket.CLOSED_STATUS, ticket.DUPLICATE_STATUS):
        return 'text-muted'
    if due < timezone.now():
        return 'text-danger'


# noinspection PyUnusedLocal
@register.simple_tag(takes_context=True)
def page_size_combo(context, *sizes, **kwargs):
    if not sizes:
        sizes = (10, 25, 50, 100, 150, 200, 500, 1000)
    page_size = get_current_page_size(context.request)
    html = 'Page Size <select class="page-size" name="page_size">'
    for size in sizes:
        selected = ('selected' if str(size) == str(page_size) else '')
        html += '<option value="{0}" {1}>{0}</option>'.format(
            size, selected)
    html += '</select>'
    return mark_safe(html)


@register.filter
def ticket_priority_label_class(value):
    from helpdesk.models import Ticket
    try:
        value = int(value) or Ticket.OPEN_STATUS
    except ValueError:
        value = Ticket.PRIORITY_NORMAL
    priorities = dict(Ticket.PRIORITY_CHOICES)
    label = priorities.get(value) or ''
    html = '<span class="label ticket-priority-{}-label">{}</span>'.format(
        value, label
    )
    return mark_safe(html)


@register.filter
def ticket_status_label_class(value):
    from helpdesk.models import Ticket
    try:
        value = int(value) or Ticket.OPEN_STATUS
    except ValueError:
        value = Ticket.OPEN_STATUS
    statuses = dict(Ticket.STATUS_CHOICES)

    status_labels = {
        Ticket.OPEN_STATUS: 'default',
        Ticket.REOPENED_STATUS: 'default',
        Ticket.DUPLICATE_STATUS: 'warning',
        Ticket.RESOLVED_STATUS: 'success',
        Ticket.CLOSED_STATUS: 'success',

    }
    label = statuses.get(value) or ''
    css = status_labels.get(value) or 'default'
    html = '<span class="label label-{}">{}</span>'.format(
        css, label
    )
    return mark_safe(html)


@register.filter
def active_icon(value):
    cls = "fa "
    if value:
        cls += 'fa-check text-success'
    else:
        cls += 'fa-close text-danger'
    return mark_safe('<span class="{}"></span>'.format(cls))


@register.simple_tag()
def disable_ifnot(*condition, attr='disabled', title='No Access!'):
    html = ''
    if not all(condition):
        html = '{} title="{}"'.format(attr, title) if title else attr
    return mark_safe(html)


@register.filter
def currency(dollars):
    if dollars is None:
        return
    dollars = round(float(dollars), 2)
    return "$%s%s" % (intcomma(int(dollars)), ("%0.2f" % dollars)[-3:])

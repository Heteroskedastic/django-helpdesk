from datetime import timedelta

from django import template
from django.utils.translation import ngettext, ugettext as _


register = template.Library()

# noinspection PyAugmentAssignment
@register.filter
def humanize_duration(seconds):
    if seconds is None:
        return
    if isinstance(seconds, timedelta):
        seconds = int(seconds.total_seconds())
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


@register.filter_function
def order_by(queryset, args):
    args = [x.strip() for x in args.split(',')]
    return queryset.order_by(*args)

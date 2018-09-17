import json

from collections import defaultdict
from datetime import date

from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, F, Case, When, Value
from django.shortcuts import render, redirect
from django.utils.dates import MONTHS_3
from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from django.utils import timezone
from django.views.generic import View, CreateView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from helpdesk.filters import TicketsFilter, CustomDateReportFilter, QueuesFilter, TicketNotificationsFilter, \
    EmailTemplatesFilter, SMSTemplatesFilter
from helpdesk.forms import TicketsBulkAssignForm, SavedSearchAddForm, QueueAddForm, QueueEditForm, \
    TicketNotificationEditForm, TicketNotificationAddForm, EmailTemplateEditForm, EmailTemplateAddForm, \
    SMSTemplateEditForm, SMSTemplateAddForm
from helpdesk.lib import safe_template_context, send_templated_mail
from helpdesk.templatetags.helpdesk_util_tags import seconds_to_time
from helpdesk.utils import StaffLoginRequiredMixin, get_current_page_size, success_message, BulkableActionMixin, \
    error_message, warning_message, to_bool, send_form_errors, to_query_dict
from helpdesk.models import Ticket, Queue, FollowUp, SavedSearch, TicketNotification, EmailTemplate, SMSTemplate
from helpdesk import settings as helpdesk_settings
from helpdesk.lib import b64decode, b64encode


User = get_user_model()


def _get_user_queues(user):
    """Return the list of Queues the user can access.

    :param user: The User (the class should have the has_perm method)
    :return: A Python list of Queues
    """
    all_queues = Queue.objects.all()
    limit_queues_by_user = \
        helpdesk_settings.HELPDESK_ENABLE_PER_QUEUE_STAFF_PERMISSION \
        and not user.has_perm('helpdesk.queue_super_access')
    if limit_queues_by_user:
        id_list = [q.pk for q in all_queues if user.has_perm(q.permission_name)]
        return all_queues.filter(pk__in=id_list)
    else:
        return all_queues


def _has_access_to_queue(user, queue):
    """Check if a certain user can access a certain queue.

    :param user: The User (the class should have the has_perm method)
    :param queue: The django-helpdesk Queue instance
    :return: True if the user has permission (either by default or explicitly), false otherwise
    """
    if user.has_perm('helpdesk.queue_super_access') or not helpdesk_settings.HELPDESK_ENABLE_PER_QUEUE_STAFF_PERMISSION:
        return True
    else:
        return user.has_perm(queue.permission_name)


def _has_access_to_saved_search(user, saved_search):
    """Check if a certain user can access a certain saved_search.

    :param user: The User (the class should have the has_perm method)
    :param saved_search: The django-helpdesk SavedSearch instance
    :return: True if the user has permission (either by default or explicitly), false otherwise
    """
    if user.has_perm('helpdesk.saved_search_super_access'):
        return True
    return saved_search.user_id == user.pk


class TicketListView(StaffLoginRequiredMixin, View):
    # noinspection PyUnusedLocal
    def _set_default_parameters(self, request, data):
        request.GET._mutable = True
        for p in ['page_size', 'order_by', 'page']:
            if request.GET.get(p):
                data.setlist(p, request.GET.getlist(p))
            elif data.get(p):
                request.GET.setlist(p, data.getlist(p))
        request.GET._mutable = False

    def get_queryset(self, **kwargs):
        time_track_qs = 'SELECT coalesce(SUM("helpdesk_tickettimetrack"."time"), INTERVAL \'0 seconds\') as sum_time FROM "helpdesk_tickettimetrack"' \
                        ' WHERE "helpdesk_tickettimetrack"."ticket_id"="helpdesk_ticket"."id"'
        money_track_qs = 'SELECT coalesce(SUM("helpdesk_ticketmoneytrack"."money"), 0) as sum_money FROM "helpdesk_ticketmoneytrack"' \
                         ' WHERE "helpdesk_ticketmoneytrack"."ticket_id"="helpdesk_ticket"."id"'
        time_open_field = Case(When(Q(status=Ticket.OPEN_STATUS) | Q(status=Ticket.REOPENED_STATUS), then=Value(timezone.now()) - F('created')),
                               default=F('modified_status') - F('created'))
        # time_track_sq = TicketTimeTrack.objects.annotate(total_time=Coalesce(Sum('time'), timedelta(0))).values_list(
        #     'total_time').filter(ticket_id=OuterRef('pk')).values('total_time')[:1]
        # money_track_sq = TicketMoneyTrack.objects.annotate(total_price=Coalesce(Sum('money'), 0)).values_list(
        #     'total_price').filter(ticket_id=OuterRef('pk')).values('total_price')[:1]
        # return Ticket.objects.annotate(
        #     time_tracks=Subquery(time_track_sq), money_tracks=Subquery(money_track_sq),
        #     time_open=time_open_field).filter(**kwargs).order_by('-id')
        return Ticket.objects.extra(select={'money_tracks': money_track_qs, 'time_tracks': time_track_qs}).annotate(
            time_open=time_open_field).filter(**kwargs).order_by('-id')

    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        user_queues = _get_user_queues(request.user)
        saved_query = data.get('saved_query')
        urlsafe_query = None
        user_saved_queries = SavedSearch.objects.filter(Q(user=request.user) | Q(shared__exact=True))
        use_default = False
        if (not saved_query) and set(data.keys()).issubset({'order_by', 'page_size', 'page'}):
            saved_query = request.user.usersettings_helpdesk.settings.get('default_ticket_saved_query')
            use_default = True

        if saved_query:
            try:
                saved_query = user_saved_queries.get(pk=int(saved_query))
            except (ValueError, SavedSearch.DoesNotExist):
                if use_default:
                    request.user.usersettings_helpdesk.update_setting({'default_ticket_saved_query': None})
                warning_message('Saved query does not exists!', request)
                return redirect(reverse('helpdesk:ticket-list'))
            try:
                data = json.loads(b64decode(str(saved_query.query)).decode())
            except ValueError:
                # Query deserialization failed. (E.g. was a pickled query)
                data = {}
            else:
                data = to_query_dict(data)
            self._set_default_parameters(request, data)

        else:
            if 'status' not in data:
                data.setlist('status', [Ticket.OPEN_STATUS, Ticket.REOPENED_STATUS, Ticket.CLOSED_STATUS])
            urlsafe_query = b64encode(json.dumps(dict(data)).encode('UTF-8'))
        qs = self.get_queryset(queue__in=user_queues)
        tickets = TicketsFilter(data, queryset=qs)

        tickets.filters['queue'].queryset = tickets.filters['queue'].queryset.filter(id__in=user_queues)
        ctx = {
            'tickets': tickets,
            'page_size': get_current_page_size(request),
            'bulk_assign_form': TicketsBulkAssignForm(),
            'urlsafe_query': urlsafe_query,
            'saved_query': saved_query,
            'user_saved_queries': user_saved_queries,
        }
        return self.render_result(request, ctx)

    def render_result(self, request, context):
        if not request.is_ajax():
            return render(request, 'helpdesk/ticket/list.html', context)
        result = []
        for t in context['tickets'].qs:
            result.append(dict(
                id=t.id, title=t.title, queue=str(t.queue), priority=t.get_priority_display(),
                money_tracks=t.money_tracks, status=t.get_status_display(), created=t.created,
                due_date=t.due_date, assigned_to=t.assigned_to and str(t.assigned_to),
                time_open=seconds_to_time(t.time_open, format='clock'),
                time_tracks=seconds_to_time(t.time_tracks, format='clock'),
            ))
        return JsonResponse(result, safe=False)


class TicketDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    model = Ticket
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.object = ticket = self.get_object()
        if not _has_access_to_queue(request.user, ticket.queue):
            error_message('No access to ticket [{}]'.format(ticket), request)
            return redirect(self.get_success_url())

        self.deleted_id = ticket.id

        ticket.delete()
        success_message('Ticket [#{} - {}] deleted successfully!'.format(self.deleted_id, ticket.title), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        referer = self.request.META.get('HTTP_REFERER')
        if (not referer) or referer.endswith(reverse('helpdesk:view', args=(self.deleted_id,))):
            return reverse('helpdesk:ticket-list')
        return referer


class TicketTakeView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    model = Ticket
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        if not _has_access_to_queue(request.user, ticket.queue):
            error_message('No access to ticket [{}]'.format(ticket), request)
            return redirect(self.get_success_url())

        if ticket.assigned_to == request.user:
            warning_message(_('This was already assigned to you!'), request)
            return redirect(self.get_success_url())

        ticket.assigned_to = request.user
        ticket.save()
        f = FollowUp(ticket=ticket,
                     date=timezone.now(),
                     title=_('Assigned to [{}]'.format(request.user.get_username())),
                     user=request.user)
        f.save()
        success_message('[{}] Ticket assigned to you successfully!'.format(ticket), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:ticket-list')


class TicketsBulkDeleteView(StaffLoginRequiredMixin, BulkableActionMixin, View):
    model = Ticket

    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        tickets = self.get_queryset()
        deleted_tickets = 0
        for ticket in tickets:
            if not _has_access_to_queue(request.user, ticket.queue):
                error_message('No access to ticket [{}]'.format(ticket), request)
                continue
            ticket.delete()
            deleted_tickets += 1

        if deleted_tickets == 0:
            warning_message('No ticket deleted!', request)
        else:
            success_message('[{}] Tickets bulk deleted!'.format(deleted_tickets), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:ticket-list')


class TicketsBulkAssignView(StaffLoginRequiredMixin, BulkableActionMixin, View):
    model = Ticket

    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        tickets = self.get_queryset()
        form = TicketsBulkAssignForm(request.POST)
        if not form.is_valid():
            send_form_errors(form, request)
            return redirect(self.get_success_url())
        user = form.cleaned_data['assigned_to']

        assigned_tickets = 0
        if user:
            title = _('Assigned to [{}] in bulk update'.format(user.get_username()))
        else:
            title = _('Unassigned in bulk update')
        for ticket in tickets:
            if not _has_access_to_queue(request.user, ticket.queue):
                error_message('No access to ticket [{}]'.format(ticket), request)
                continue
            if ticket.assigned_to == user:
                continue

            ticket.assigned_to = user
            ticket.save()
            f = FollowUp(ticket=ticket,
                         date=timezone.now(),
                         title=title,
                         public=True,
                         user=request.user)
            f.save()
            assigned_tickets += 1

        if assigned_tickets == 0:
            warning_message('No ticket {}!'.format('assigned' if user else 'unassigned'), request)
        else:
            success_message('[{}] Tickets {}!'.format(assigned_tickets, title), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:ticket-list')


class TicketsBulkCloseView(StaffLoginRequiredMixin, BulkableActionMixin, View):
    model = Ticket

    def _close_ticket(self, request, ticket, send_mail=False):
        if ticket.status == Ticket.CLOSED_STATUS:
            return False
        now = timezone.now()
        if not send_mail:
            ticket.status = Ticket.CLOSED_STATUS
            ticket.modified_status = now
            ticket.save()
            f = FollowUp(ticket=ticket,
                         date=now,
                         title=_('Closed in bulk update'),
                         public=False,
                         user=request.user,
                         new_status=Ticket.CLOSED_STATUS)
            f.save()
        else:
            ticket.status = Ticket.CLOSED_STATUS
            ticket.modified_status = now
            ticket.save()
            f = FollowUp(ticket=ticket,
                         date=now,
                         title=_('Closed in bulk update'),
                         public=True,
                         user=request.user,
                         new_status=Ticket.CLOSED_STATUS)
            f.save()
            # Send email to Submitter, Owner, Queue CC
            context = safe_template_context(ticket)
            context.update(resolution=ticket.resolution)

            messages_sent_to = []

            if ticket.submitter_email:
                send_templated_mail(
                    'closed_submitter',
                    context,
                    recipients=ticket.submitter_email,
                    sender=ticket.queue.from_address,
                    fail_silently=True,
                )
                messages_sent_to.append(ticket.submitter_email)

            for cc in ticket.ticketcc_set.all():
                if cc.email_address not in messages_sent_to:
                    send_templated_mail(
                        'closed_submitter',
                        context,
                        recipients=cc.email_address,
                        sender=ticket.queue.from_address,
                        fail_silently=True,
                    )
                    messages_sent_to.append(cc.email_address)

            if ticket.assigned_to and \
                    request.user != ticket.assigned_to and \
                    ticket.assigned_to.email and \
                    ticket.assigned_to.email not in messages_sent_to:
                send_templated_mail(
                    'closed_owner',
                    context,
                    recipients=ticket.assigned_to.email,
                    sender=ticket.queue.from_address,
                    fail_silently=True,
                )
                messages_sent_to.append(ticket.assigned_to.email)

            if ticket.queue.updated_ticket_cc and \
                            ticket.queue.updated_ticket_cc not in messages_sent_to:
                send_templated_mail(
                    'closed_cc',
                    context,
                    recipients=ticket.queue.updated_ticket_cc,
                    sender=ticket.queue.from_address,
                    fail_silently=True,
                )
        return True
    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        tickets = self.get_queryset()
        closed_tickets = 0
        send_mail = to_bool(request.POST.get('send_mail'))
        for ticket in tickets:
            if not _has_access_to_queue(request.user, ticket.queue):
                error_message('No access to ticket [{}]'.format(ticket), request)
                continue
            closed = self._close_ticket(request, ticket, send_mail=send_mail)
            if closed:
                closed_tickets += 1

        if closed_tickets == 0:
            warning_message('No ticket closed!', request)
        else:
            success_message('[{}] Tickets bulk closed!'.format(closed_tickets), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:ticket-list')


class SavedSearchListView(StaffLoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        saved_queries = SavedSearch.objects.order_by('id')
        ctx = {'saved_queries': saved_queries}
        return render(request, "helpdesk/saved_search/list.html", ctx)


class SavedSearchAddView(StaffLoginRequiredMixin, CreateView):
    model = SavedSearch
    form_class = SavedSearchAddForm

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user
        self.object.save()
        success_message('Added New Query: [{}]'.format(self.object), self.request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return '{}?saved_query={}'.format(reverse('helpdesk:ticket-list'), self.object.pk)


class SavedSearchDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    pk_url_kwarg = 'pk'
    model = SavedSearch

    def post(self, request, *args, **kwargs):
        saved_search = self.get_object()
        if not _has_access_to_saved_search(request.user, saved_search):
            error_message('No Permission to delete [{}] saved query!'.format(saved_search), self.request)
            return redirect(self.get_success_url())

        saved_search.delete()
        success_message('Query [{}] deleted successfully!'.format(saved_search), self.request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:saved_search-list')


class SavedSearchSetDefaultView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    pk_url_kwarg = 'pk'
    model = SavedSearch

    def post(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        self.object = None
        if pk != '0':
            self.object = self.get_object()
        request.user.usersettings_helpdesk.update_setting(
            {'default_ticket_saved_query': self.object and self.object.pk})
        if self.object:
            success_message('Set Query [{}] as a default!'.format(self.object), self.request)
        else:
            success_message('Removed default query!', self.request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:saved_search-list')


class SavedSearchSwitchSharedView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    pk_url_kwarg = 'pk'
    model = SavedSearch

    def post(self, request, *args, **kwargs):
        saved_search = self.get_object()
        if not _has_access_to_saved_search(request.user, saved_search):
            error_message('No Permission to modify [{}] saved query!'.format(saved_search), self.request)
            return redirect(self.get_success_url())

        saved_search.shared = not saved_search.shared
        saved_search.save(update_fields=['shared'])
        success_message('Query [{}] {} successfully!'.format(
            saved_search, 'shared' if saved_search.shared else 'un-shared'), self.request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:saved_search-list')


class RunStatView(StaffLoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        report = kwargs.get('report')
        if report not in ('queuemonth', 'usermonth', 'queuestatus', 'queuepriority', 'userstatus', 'userpriority',
                          'userqueue', 'daysuntilticketclosedbymonth') or Ticket.objects.all().count() == 0:
            return redirect(reverse("helpdesk:stat_index"))

        user_queues = _get_user_queues(request.user)
        report_queryset = Ticket.objects.all().select_related().filter(queue__in=user_queues)

        from_saved_query = False
        saved_query = request.GET.get('saved_query', None)
        user_saved_queries = SavedSearch.objects.filter(Q(user=request.user) | Q(shared__exact=True))

        if saved_query:
            try:
                saved_query = user_saved_queries.get(pk=int(saved_query))
            except (ValueError, SavedSearch.DoesNotExist):
                warning_message('Saved query does not exists!', request)
                return redirect(reverse('helpdesk:stat_index'))

            try:
                query_params = json.loads(b64decode(str(saved_query.query)).decode())
            except ValueError:
                return redirect(reverse('helpdesk:stat_index'))
            else:
                query_params = to_query_dict(query_params)

            report_queryset = TicketsFilter(query_params, queryset=report_queryset).qs

        summarytable = defaultdict(int)
        # a second table for more complex queries
        summarytable2 = defaultdict(int)

        def month_name(m):
            MONTHS_3[m].title()

        first_ticket = Ticket.objects.all().order_by('created').first()
        first_month = first_ticket.created.month
        first_year = first_ticket.created.year

        last_ticket = Ticket.objects.all().order_by('created').last()
        last_month = last_ticket.created.month
        last_year = last_ticket.created.year

        periods = []
        year, month = first_year, first_month
        working = True
        periods.append("%s-%s" % (year, month))

        while working:
            month += 1
            if month > 12:
                year += 1
                month = 1
            if (year > last_year) or (month > last_month and year >= last_year):
                working = False
            periods.append("%s-%s" % (year, month))

        title = col1heading = possible_options = charttype = None
        if report == 'userpriority':
            title = _('User by Priority')
            col1heading = _('User')
            possible_options = [t[1].title() for t in Ticket.PRIORITY_CHOICES]
            charttype = 'bar'

        elif report == 'userqueue':
            title = _('User by Queue')
            col1heading = _('User')
            possible_options = [q.title for q in user_queues]
            charttype = 'bar'

        elif report == 'userstatus':
            title = _('User by Status')
            col1heading = _('User')
            possible_options = [s[1].title() for s in Ticket.STATUS_CHOICES]
            charttype = 'bar'

        elif report == 'usermonth':
            title = _('User by Month')
            col1heading = _('User')
            possible_options = periods
            charttype = 'date'

        elif report == 'queuepriority':
            title = _('Queue by Priority')
            col1heading = _('Queue')
            possible_options = [t[1].title() for t in Ticket.PRIORITY_CHOICES]
            charttype = 'bar'

        elif report == 'queuestatus':
            title = _('Queue by Status')
            col1heading = _('Queue')
            possible_options = [s[1].title() for s in Ticket.STATUS_CHOICES]
            charttype = 'bar'

        elif report == 'queuemonth':
            title = _('Queue by Month')
            col1heading = _('Queue')
            possible_options = periods
            charttype = 'date'

        elif report == 'daysuntilticketclosedbymonth':
            title = _('Days until ticket closed by Month')
            col1heading = _('Queue')
            possible_options = periods
            charttype = 'date'

        metric3 = False
        for ticket in report_queryset:
            if report == 'userpriority':
                metric1 = u'%s' % ticket.get_assigned_to
                metric2 = u'%s' % ticket.get_priority_display()

            elif report == 'userqueue':
                metric1 = u'%s' % ticket.get_assigned_to
                metric2 = u'%s' % ticket.queue.title

            elif report == 'userstatus':
                metric1 = u'%s' % ticket.get_assigned_to
                metric2 = u'%s' % ticket.get_status_display()

            elif report == 'usermonth':
                metric1 = u'%s' % ticket.get_assigned_to
                metric2 = u'%s-%s' % (ticket.created.year, ticket.created.month)

            elif report == 'queuepriority':
                metric1 = u'%s' % ticket.queue.title
                metric2 = u'%s' % ticket.get_priority_display()

            elif report == 'queuestatus':
                metric1 = u'%s' % ticket.queue.title
                metric2 = u'%s' % ticket.get_status_display()

            elif report == 'queuemonth':
                metric1 = u'%s' % ticket.queue.title
                metric2 = u'%s-%s' % (ticket.created.year, ticket.created.month)

            elif report == 'daysuntilticketclosedbymonth':
                metric1 = u'%s' % ticket.queue.title
                metric2 = u'%s-%s' % (ticket.created.year, ticket.created.month)
                metric3 = ticket.modified - ticket.created
                metric3 = metric3.days

            summarytable[metric1, metric2] += 1
            if metric3:
                if report == 'daysuntilticketclosedbymonth':
                    summarytable2[metric1, metric2] += metric3

        table = []

        if report == 'daysuntilticketclosedbymonth':
            for key in summarytable2.keys():
                summarytable[key] = summarytable2[key] / summarytable[key]

        header1 = sorted(set(list(i for i, _ in summarytable.keys())))

        column_headings = [col1heading] + possible_options

        # Pivot the data so that 'header1' fields are always first column
        # in the row, and 'possible_options' are always the 2nd - nth columns.
        for item in header1:
            data = []
            for hdr in possible_options:
                data.append(summarytable[item, hdr])
            table.append([item] + data)

        # Zip data and headers together in one list for Morris.js charts
        # will get a list like [(Header1, Data1), (Header2, Data2)...]
        seriesnum = 0
        morrisjs_data = []
        for label in column_headings[1:]:
            seriesnum += 1
            datadict = {"x": label}
            for n in range(0, len(table)):
                datadict[n] = table[n][seriesnum]
            morrisjs_data.append(datadict)

        series_names = []
        for series in table:
            series_names.append(series[0])

        return render(request, 'helpdesk/stat_output.html', {
            'title': title,
            'charttype': charttype,
            'data': table,
            'headings': column_headings,
            'series_names': series_names,
            'morrisjs_data': morrisjs_data,
            'from_saved_query': from_saved_query,
            'saved_query': saved_query,
            'user_saved_queries': user_saved_queries,
        })


class CustomDateReportView(StaffLoginRequiredMixin, View):

    def get_queryset(self, **kwargs):
        time_track_qs = 'SELECT coalesce(SUM("helpdesk_tickettimetrack"."time"), INTERVAL \'0 seconds\') as sum_time FROM "helpdesk_tickettimetrack"' \
                        ' WHERE "helpdesk_tickettimetrack"."ticket_id"="helpdesk_ticket"."id"'
        money_track_qs = 'SELECT coalesce(SUM("helpdesk_ticketmoneytrack"."money"), 0) as sum_money FROM "helpdesk_ticketmoneytrack"' \
                         ' WHERE "helpdesk_ticketmoneytrack"."ticket_id"="helpdesk_ticket"."id"'
        closed_at_field = Case(When(Q(status=Ticket.CLOSED_STATUS), then=F('modified_status')), default=None)
        # closed_at_null will be used for sorting to show null values at end for desc sorting
        closed_at_null = Case(When(Q(status=Ticket.CLOSED_STATUS), then=F('modified_status')), default=date(1, 1, 1))
        return Ticket.objects.extra(select={'money_tracks': money_track_qs, 'time_tracks': time_track_qs}).annotate(
            closed_at=closed_at_field, closed_at_null=closed_at_null).filter(**kwargs).order_by('-id')

    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        user_queues = _get_user_queues(request.user)
        qs = self.get_queryset(queue__in=user_queues)
        filter_form = CustomDateReportFilter(data, queryset=qs).form
        filter_form.is_valid()
        filter_data = filter_form.cleaned_data
        if not filter_data.get('created_min') and not filter_data.get('created_max') and not filter_data.get('date_range'):
            filter_data['date_range'] = data['date_range'] = 'this_month'
        if filter_data.get('date_range'):
            min_date, max_date = CustomDateReportFilter.get_range_by_name(data.get('date_range'))
            data['created_min'] = str(min_date)
            data['created_max'] = str(max_date)
        else:
            if not filter_data.get('created_min'):
                data['created_min'] = data['created_max']
            elif not filter_data.get('created_max'):
                data['created_max'] = data['created_min']
        tickets = CustomDateReportFilter(data, queryset=qs)
        ctx = {
            'date_range': tickets.get_range_display(),
            'date_range_choices': tickets.DATE_RANGE_CHOICES,
            'tickets': tickets,
            'page_size': get_current_page_size(request),
        }
        return self.render_result(request, ctx)

    def render_result(self, request, context):
        if not request.is_ajax():
            return render(request, 'helpdesk/report/custom-date/page.html', context)
        result = []
        for t in context['tickets'].qs:
            time_tracks = t.total_time_tracked()
            if time_tracks:
                time_tracks = '{}hr over {} D'.format(
                    seconds_to_time(time_tracks, format='hour'), t.records_time_tracked())
            result.append(dict(
                id=t.id, title=t.title, queue=str(t.queue), priority=t.get_priority_display(),
                money_tracks=t.money_tracks, status=t.get_status_display(), created=t.created.date(),
                closed_at=t.closed_at and t.closed_at.date(),
                due_date=t.due_date, assigned_to=t.assigned_to and str(t.assigned_to),
                time_tracks=time_tracks,
            ))
        return JsonResponse(result, safe=False)


# noinspection PyMethodMayBeStatic
class QueueListView(StaffLoginRequiredMixin, View):
    permission_required = 'helpdesk.view_queue'
    template_name = "helpdesk/queue/list.html"

    # noinspection PyUnusedLocal
    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        queues = QueuesFilter(data, queryset=Queue.objects.order_by('-id').all())
        ctx = {'queues': queues, 'page_size': get_current_page_size(request)}
        return render(request, self.template_name, ctx)


class QueueAddView(StaffLoginRequiredMixin, CreateView):
    permission_required = 'helpdesk.add_queue'
    form_class = QueueAddForm
    template_name = "helpdesk/queue/add.html"

    def form_valid(self, form):
        result = super(QueueAddView, self).form_valid(form)
        success_message('Queue "{}" created successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:queue-list')


class QueueEditView(StaffLoginRequiredMixin, UpdateView):
    permission_required = 'helpdesk.view_queue'
    pk_url_kwarg = 'pk'
    form_class = QueueEditForm
    model = Queue
    template_name = 'helpdesk/queue/edit.html'

    def form_valid(self, form):
        result = super(QueueEditView, self).form_valid(form)
        success_message('Queue "{}" updated successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:queue-list')


class QueueDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    permission_required = 'helpdesk.delete_queue'
    model = Queue
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    def post(self, request, *args, **kwargs):
        queue = self.get_object()
        queue_display = str(queue)
        queue.delete()
        success_message('Queue "{}" deleted successfully!'.format(queue_display), self.request)
        return redirect(reverse('helpdesk:queue-list'))


# noinspection PyMethodMayBeStatic
class TicketNotificationListView(StaffLoginRequiredMixin, View):
    permission_required = 'helpdesk.view_ticketnotification'
    template_name = "helpdesk/ticket_notification/list.html"

    # noinspection PyUnusedLocal
    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        ticket_notifications = TicketNotificationsFilter(data, queryset=TicketNotification.objects.order_by('-id').all())
        ctx = {'ticket_notifications': ticket_notifications, 'page_size': get_current_page_size(request)}
        return render(request, self.template_name, ctx)


class TicketNotificationAddView(StaffLoginRequiredMixin, CreateView):
    permission_required = 'helpdesk.add_ticketnotification'
    form_class = TicketNotificationAddForm
    template_name = "helpdesk/ticket_notification/add.html"

    def form_valid(self, form):
        result = super(TicketNotificationAddView, self).form_valid(form)
        success_message('Ticket Notification "{}" created successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:ticket_notification-list')


class TicketNotificationEditView(StaffLoginRequiredMixin, UpdateView):
    permission_required = 'helpdesk.view_ticketnotification'
    pk_url_kwarg = 'pk'
    form_class = TicketNotificationEditForm
    model = TicketNotification
    template_name = 'helpdesk/ticket_notification/edit.html'

    def form_valid(self, form):
        result = super(TicketNotificationEditView, self).form_valid(form)
        success_message('Ticket Notification "{}" updated successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:ticket_notification-list')


class TicketNotificationDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    permission_required = 'helpdesk.delete_ticketnotification'
    model = TicketNotification
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    def post(self, request, *args, **kwargs):
        ticket_notification = self.get_object()
        ticket_notification_display = str(ticket_notification)
        ticket_notification.delete()
        success_message('Ticket Notification "{}" deleted successfully!'.format(ticket_notification_display), self.request)
        return redirect(reverse('helpdesk:ticket_notification-list'))


# noinspection PyMethodMayBeStatic
class EmailTemplateListView(StaffLoginRequiredMixin, View):
    permission_required = 'helpdesk.view_emailtemplate'
    template_name = "helpdesk/email_template/list.html"

    # noinspection PyUnusedLocal
    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        email_templates = EmailTemplatesFilter(data, queryset=EmailTemplate.objects.order_by('-id').all())
        ctx = {'email_templates': email_templates, 'page_size': get_current_page_size(request)}
        return render(request, self.template_name, ctx)


class EmailTemplateAddView(StaffLoginRequiredMixin, CreateView):
    permission_required = 'helpdesk.add_emailtemplate'
    form_class = EmailTemplateAddForm
    template_name = "helpdesk/email_template/add.html"

    def form_valid(self, form):
        result = super(EmailTemplateAddView, self).form_valid(form)
        success_message('Email Template "{}" created successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:email_template-list')


class EmailTemplateEditView(StaffLoginRequiredMixin, UpdateView):
    permission_required = 'helpdesk.view_emailtemplate'
    pk_url_kwarg = 'pk'
    form_class = EmailTemplateEditForm
    model = EmailTemplate
    template_name = 'helpdesk/email_template/edit.html'

    def form_valid(self, form):
        result = super(EmailTemplateEditView, self).form_valid(form)
        success_message('Email Template "{}" updated successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:email_template-list')


class EmailTemplateDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    permission_required = 'helpdesk.delete_emailtemplate'
    model = EmailTemplate
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    def post(self, request, *args, **kwargs):
        email_template = self.get_object()
        email_template_display = str(email_template)
        email_template.delete()
        success_message('Email Template "{}" deleted successfully!'.format(email_template_display), self.request)
        return redirect(reverse('helpdesk:email_template-list'))


# noinspection PyMethodMayBeStatic
class SMSTemplateListView(StaffLoginRequiredMixin, View):
    permission_required = 'helpdesk.view_emailtemplate'
    template_name = "helpdesk/sms_template/list.html"

    # noinspection PyUnusedLocal
    def get(self, request, *args, **kwargs):
        data = request.GET.copy()
        sms_templates = SMSTemplatesFilter(data, queryset=SMSTemplate.objects.order_by('-id').all())
        ctx = {'sms_templates': sms_templates, 'page_size': get_current_page_size(request)}
        return render(request, self.template_name, ctx)


class SMSTemplateAddView(StaffLoginRequiredMixin, CreateView):
    permission_required = 'helpdesk.add_emailtemplate'
    form_class = SMSTemplateAddForm
    template_name = "helpdesk/sms_template/add.html"

    def form_valid(self, form):
        result = super(SMSTemplateAddView, self).form_valid(form)
        success_message('SMS Template "{}" created successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:sms_template-list')


class SMSTemplateEditView(StaffLoginRequiredMixin, UpdateView):
    permission_required = 'helpdesk.view_emailtemplate'
    pk_url_kwarg = 'pk'
    form_class = SMSTemplateEditForm
    model = SMSTemplate
    template_name = 'helpdesk/sms_template/edit.html'

    def form_valid(self, form):
        result = super(SMSTemplateEditView, self).form_valid(form)
        success_message('SMS Template "{}" updated successfully.'.format(
            self.object), self.request)
        return result

    def get_success_url(self):
        return reverse('helpdesk:sms_template-list')


class SMSTemplateDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    permission_required = 'helpdesk.delete_emailtemplate'
    model = SMSTemplate
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    def post(self, request, *args, **kwargs):
        sms_template = self.get_object()
        sms_template_display = str(sms_template)
        sms_template.delete()
        success_message('SMS Template "{}" deleted successfully!'.format(sms_template_display), self.request)
        return redirect(reverse('helpdesk:sms_template-list'))

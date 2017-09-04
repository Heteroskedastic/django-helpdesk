import json
from django.http import QueryDict
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum, F, Case, When, Value
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from django.utils import timezone
from django.views.generic import View, CreateView
from django.views.generic.detail import SingleObjectMixin

from helpdesk.filters import TicketsFilter
from helpdesk.forms import TicketsBulkAssignForm, SavedSearchAddForm
from helpdesk.lib import safe_template_context, send_templated_mail
from helpdesk.utils import StaffLoginRequiredMixin, get_current_page_size, success_message, BulkableActionMixin, \
    error_message, warning_message, to_bool, send_form_errors, to_query_dict
from helpdesk.models import Ticket, Queue, FollowUp, SavedSearch, TicketTimeTrack
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
        and not user.is_superuser
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
    if user.is_superuser or not helpdesk_settings.HELPDESK_ENABLE_PER_QUEUE_STAFF_PERMISSION:
        return True
    else:
        return user.has_perm(queue.permission_name)


def _has_access_to_saved_search(user, saved_search):
    """Check if a certain user can access a certain saved_search.

    :param user: The User (the class should have the has_perm method)
    :param saved_search: The django-helpdesk SavedSearch instance
    :return: True if the user has permission (either by default or explicitly), false otherwise
    """
    if user.is_superuser:
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
                return redirect('helpdesk:ticket-list')
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
        return render(request, 'helpdesk/ticket/list.html', ctx)


class TicketDeleteView(StaffLoginRequiredMixin, SingleObjectMixin, View):
    model = Ticket
    pk_url_kwarg = 'pk'

    # noinspection PyUnusedLocal
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        if not _has_access_to_queue(request.user, ticket.queue):
            error_message('No access to ticket [{}]'.format(ticket), request)
            return redirect(self.get_success_url())

        ticket_id = ticket.id
        ticket.delete()
        success_message('Ticket [#{} - {}] deleted successfully!'.format(ticket_id, ticket.title), request)
        return redirect(self.get_success_url())

    # noinspection PyMethodMayBeStatic
    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER') or reverse('helpdesk:ticket-list')


class TicketHoldView(StaffLoginRequiredMixin, SingleObjectMixin, View):
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



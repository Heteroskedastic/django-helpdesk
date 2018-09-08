"""
django-helpdesk - A Django powered ticket tracker for small enterprise.

(c) Copyright 2008 Jutda. All Rights Reserved. See LICENSE for details.

views/staff.py - The bulk of the application - provides most business logic and
                 renders all staff-facing views.
"""
from __future__ import unicode_literals

import traceback
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError, PermissionDenied
from django.core import paginator
from django.db import connection
from django.db.models import Q
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils.dates import MONTHS_3
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext as _
from django.utils.html import escape
from django import forms
from django.utils import timezone
from django.views.generic import CreateView, UpdateView, DeleteView
from django.views.generic.detail import SingleObjectMixin

from helpdesk.forms import (
    TicketForm, UserSettingsForm, EmailIgnoreForm, EditTicketForm, TicketCCForm,
    TicketCCEmailForm, TicketCCUserForm, EditFollowUpForm, TicketDependencyForm,
    TicketTimeTrackForm, TicketMoneyTrackForm)
from helpdesk.lib import (
    send_templated_mail, query_to_dict, apply_query, safe_template_context,
    process_attachments,
)
from helpdesk.models import (
    Ticket, Queue, FollowUp, TicketChange, PreSetReply, Attachment, SavedSearch,
    IgnoreEmail, TicketCC, TicketDependency,
    TicketTimeTrack, TicketMoneyTrack)
from helpdesk import settings as helpdesk_settings

User = get_user_model()


if helpdesk_settings.HELPDESK_ALLOW_NON_STAFF_TICKET_UPDATE:
    # treat 'normal' users like 'staff'
    staff_member_required = user_passes_test(
        lambda u: u.is_authenticated() and u.is_active)
else:
    staff_member_required = user_passes_test(
        lambda u: u.is_authenticated() and u.is_active and u.is_staff)


superuser_required = user_passes_test(
    lambda u: u.is_authenticated() and u.is_active and u.is_superuser)


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


def dashboard(request):
    """
    A quick summary overview for users: A list of their own tickets, a table
    showing ticket counts by queue/status, and a list of unassigned tickets
    with options for them to 'Take' ownership of said tickets.
    """

    # open & reopened & resolved tickets, assigned to current user
    tickets = Ticket.objects.select_related('queue').filter(assigned_to=request.user).filter(
        status__in=[Ticket.OPEN_STATUS, Ticket.REOPENED_STATUS, Ticket.RESOLVED_STATUS]).order_by('priority', '-id')

    # closed & resolved tickets, assigned to current user
    tickets_closed_resolved = Ticket.objects.select_related('queue').filter(
        assigned_to=request.user, status__in=[Ticket.CLOSED_STATUS, Ticket.RESOLVED_STATUS]).order_by('-id')

    user_queues = _get_user_queues(request.user)

    unassigned_tickets = Ticket.objects.select_related('queue').filter(
        assigned_to__isnull=True, queue__in=user_queues
    ).exclude(status=Ticket.CLOSED_STATUS).order_by('priority', '-id')

    # all tickets, reported by current user
    all_tickets_reported_by_current_user = ''
    email_current_user = request.user.email
    if email_current_user:
        all_tickets_reported_by_current_user = Ticket.objects.select_related('queue').filter(
            submitter_email=email_current_user,
        ).order_by('status', 'priority', '-id')

    tickets_in_queues = Ticket.objects.filter(
        queue__in=user_queues,
    )
    basic_ticket_stats = calc_basic_ticket_stats(tickets_in_queues)

    # The following query builds a grid of queues & ticket statuses,
    # to be displayed to the user. EG:
    #          Open  Resolved
    # Queue 1    10     4
    # Queue 2     4    12

    queues = _get_user_queues(request.user).values_list('id', flat=True)

    from_clause = """FROM    helpdesk_ticket t,
                    helpdesk_queue q"""
    if queues:
        where_clause = """WHERE   q.id = t.queue_id AND
                        q.id IN (%s)""" % (",".join(("%d" % pk for pk in queues)))
    else:
        where_clause = """WHERE   q.id = t.queue_id"""

    cursor = connection.cursor()
    cursor.execute("""
        SELECT      q.id as queue,
                    q.title AS name,
                    COUNT(CASE t.status WHEN '1' THEN t.id WHEN '2' THEN t.id END) AS open,
                    COUNT(CASE t.status WHEN '3' THEN t.id END) AS resolved,
                    COUNT(CASE t.status WHEN '4' THEN t.id END) AS closed
            %s
            %s
            GROUP BY queue, name
            ORDER BY q.id;
    """ % (from_clause, where_clause))

    return render(request, 'helpdesk/dashboard.html', {
        'user_tickets': tickets,
        'user_tickets_closed_resolved': tickets_closed_resolved,
        'unassigned_tickets': unassigned_tickets,
        'all_tickets_reported_by_current_user': all_tickets_reported_by_current_user,
        'basic_ticket_stats': basic_ticket_stats,
    })
dashboard = staff_member_required(dashboard)


def delete_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    if request.method == 'GET':
        return render(request, 'helpdesk/delete_ticket.html', {
            'ticket': ticket,
        })
    else:
        ticket.delete()
        return HttpResponseRedirect(reverse('helpdesk:home'))
delete_ticket = staff_member_required(delete_ticket)


def followup_edit(request, ticket_id, followup_id):
    """Edit followup options with an ability to change the ticket."""
    followup = get_object_or_404(FollowUp, id=followup_id)
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()
    if request.method == 'GET':
        form = EditFollowUpForm(initial={
            'title': escape(followup.title),
            'ticket': followup.ticket,
            'comment': escape(followup.comment),
            'public': followup.public,
            'new_status': followup.new_status,
        })

        ticketcc_string, show_subscribe = \
            return_ticketccstring_and_show_subscribe(request.user, ticket)

        return render(request, 'helpdesk/followup_edit.html', {
            'followup': followup,
            'ticket': ticket,
            'form': form,
            'ticketcc_string': ticketcc_string,
        })
    elif request.method == 'POST':
        form = EditFollowUpForm(request.POST)
        if form.is_valid():
            title = form.cleaned_data['title']
            _ticket = form.cleaned_data['ticket']
            comment = form.cleaned_data['comment']
            public = form.cleaned_data['public']
            new_status = form.cleaned_data['new_status']
            # will save previous date
            old_date = followup.date
            new_followup = FollowUp(title=title, date=old_date, ticket=_ticket, comment=comment, public=public, new_status=new_status, )
            # keep old user if one did exist before.
            if followup.user:
                new_followup.user = followup.user
            new_followup.save()
            # get list of old attachments & link them to new_followup
            attachments = Attachment.objects.filter(followup=followup)
            for attachment in attachments:
                attachment.followup = new_followup
                attachment.save()
            # delete old followup
            followup.delete()
        return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket.id]))
followup_edit = staff_member_required(followup_edit)


def followup_delete(request, ticket_id, followup_id):
    """followup delete for superuser"""

    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket.id]))

    followup = get_object_or_404(FollowUp, id=followup_id)
    followup.delete()
    return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket.id]))
followup_delete = staff_member_required(followup_delete)


def view_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    if 'take' in request.GET:
        # Allow the user to assign the ticket to themselves whilst viewing it.

        # Trick the update_ticket() view into thinking it's being called with
        # a valid POST.
        request.POST = {
            'owner': request.user.id,
            'public': 1,
            'title': ticket.title,
            'comment': ''
        }
        return update_ticket(request, ticket_id)

    if 'subscribe' in request.GET:
        # Allow the user to subscribe him/herself to the ticket whilst viewing it.
        ticket_cc, show_subscribe = \
            return_ticketccstring_and_show_subscribe(request.user, ticket)
        if show_subscribe:
            subscribe_staff_member_to_ticket(ticket, request.user)
            return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket.id]))

    if 'close' in request.GET and ticket.status == Ticket.RESOLVED_STATUS:
        if not ticket.assigned_to:
            owner = 0
        else:
            owner = ticket.assigned_to.id

        # Trick the update_ticket() view into thinking it's being called with
        # a valid POST.
        request.POST = {
            'new_status': Ticket.CLOSED_STATUS,
            'public': 1,
            'owner': owner,
            'title': ticket.title,
            'comment': _('Accepted resolution and closed ticket'),
        }

        return update_ticket(request, ticket_id)

    if helpdesk_settings.HELPDESK_STAFF_ONLY_TICKET_OWNERS:
        users = User.objects.filter(is_active=True, is_staff=True).order_by(User.USERNAME_FIELD)
    else:
        users = User.objects.filter(is_active=True).order_by(User.USERNAME_FIELD)

    # TODO: shouldn't this template get a form to begin with?
    form = TicketForm(initial={'due_date': ticket.due_date, 'title': ticket.title,
                               'assigned_to': ticket.assigned_to})

    ticketcc_string, show_subscribe = \
        return_ticketccstring_and_show_subscribe(request.user, ticket)

    return render(request, 'helpdesk/ticket.html', {
        'ticket': ticket,
        'form': form,
        'active_users': users,
        'priorities': Ticket.PRIORITY_CHOICES,
        'preset_replies': PreSetReply.objects.filter(
            Q(queues=ticket.queue) | Q(queues__isnull=True)),
        'ticketcc_string': ticketcc_string,
        'SHOW_SUBSCRIBE': show_subscribe,
    })
view_ticket = staff_member_required(view_ticket)


def return_ticketccstring_and_show_subscribe(user, ticket):
    """used in view_ticket() and followup_edit()"""
    # create the ticketcc_string and check whether current user is already
    # subscribed
    username = user.get_username().upper()
    useremail = user.email.upper()
    strings_to_check = list()
    strings_to_check.append(username)
    strings_to_check.append(useremail)

    ticketcc_string = ''
    all_ticketcc = ticket.ticketcc_set.all()
    counter_all_ticketcc = len(all_ticketcc) - 1
    show_subscribe = True
    for i, ticketcc in enumerate(all_ticketcc):
        ticketcc_this_entry = str(ticketcc.display)
        ticketcc_string += ticketcc_this_entry
        if i < counter_all_ticketcc:
            ticketcc_string += ', '
        if strings_to_check.__contains__(ticketcc_this_entry.upper()):
            show_subscribe = False

    # check whether current user is a submitter or assigned to ticket
    assignedto_username = str(ticket.assigned_to).upper()
    strings_to_check = list()
    if ticket.submitter_email is not None:
        submitter_email = ticket.submitter_email.upper()
        strings_to_check.append(submitter_email)
    strings_to_check.append(assignedto_username)
    if strings_to_check.__contains__(username) or strings_to_check.__contains__(useremail):
        show_subscribe = False

    return ticketcc_string, show_subscribe


def subscribe_staff_member_to_ticket(ticket, user):
    """used in view_ticket() and update_ticket()"""
    ticketcc = TicketCC(
        ticket=ticket,
        user=user,
        can_view=True,
        can_update=True,
    )
    ticketcc.save()


def update_ticket(request, ticket_id, public=False):
    if not (public or (
            request.user.is_authenticated() and
            request.user.is_active and (
                request.user.is_staff or
                helpdesk_settings.HELPDESK_ALLOW_NON_STAFF_TICKET_UPDATE))):
        return HttpResponseRedirect('%s?next=%s' %
                                    (reverse('helpdesk:login'), request.path))

    ticket = get_object_or_404(Ticket, id=ticket_id)

    comment = request.POST.get('comment', '')
    new_status = int(request.POST.get('new_status', ticket.status))
    title = request.POST.get('title', '')
    public = request.POST.get('public', False)
    owner = int(request.POST.get('owner', -1))
    priority = int(request.POST.get('priority', ticket.priority))
    old_due_date = ticket.due_date
    try:
        due_date = datetime.strptime(request.POST.get('due_date', ''), '%Y-%m-%d').date()
    except ValueError:
        due_date = old_due_date

    no_changes = all([
        not request.FILES,
        not comment,
        new_status == ticket.status,
        title == ticket.title,
        priority == int(ticket.priority),
        due_date == old_due_date,
        (owner == -1) or (not owner and not ticket.assigned_to) or
        (owner and User.objects.get(id=owner) == ticket.assigned_to),
    ])
    if no_changes:
        return return_to_ticket(request.user, helpdesk_settings, ticket)

    # We need to allow the 'ticket' and 'queue' contexts to be applied to the
    # comment.
    context = safe_template_context(ticket)

    from django.template import engines
    template_func = engines['django'].from_string
    # this prevents system from trying to render any template tags
    # broken into two stages to prevent changes from first replace being themselves
    # changed by the second replace due to conflicting syntax
    comment = comment.replace('{%', 'X-HELPDESK-COMMENT-VERBATIM').replace('%}', 'X-HELPDESK-COMMENT-ENDVERBATIM')
    comment = comment.replace('X-HELPDESK-COMMENT-VERBATIM', '{% verbatim %}{%').replace('X-HELPDESK-COMMENT-ENDVERBATIM', '%}{% endverbatim %}')
    # render the neutralized template
    comment = template_func(comment).render(context)

    if owner is -1 and ticket.assigned_to:
        owner = ticket.assigned_to.id

    f = FollowUp(ticket=ticket, date=timezone.now(), comment=comment)

    if request.user.is_staff or helpdesk_settings.HELPDESK_ALLOW_NON_STAFF_TICKET_UPDATE:
        f.user = request.user

    f.public = public

    reassigned = False

    old_owner = ticket.assigned_to
    if owner is not -1:
        if owner != 0 and ((ticket.assigned_to and owner != ticket.assigned_to.id) or not ticket.assigned_to):
            new_user = User.objects.get(id=owner)
            f.title = _('Assigned to %(username)s') % {
                'username': new_user.get_username(),
            }
            ticket.assigned_to = new_user
            reassigned = True
        # user changed owner to 'unassign'
        elif owner == 0 and ticket.assigned_to is not None:
            f.title = _('Unassigned')
            ticket.assigned_to = None

    old_status_str = ticket.get_status_display()
    old_status = ticket.status
    if new_status != ticket.status:
        ticket.status = new_status
        ticket.modified_status = f.date
        ticket.save()
        f.new_status = new_status
        if f.title:
            f.title += ' and %s' % ticket.get_status_display()
        else:
            f.title = '%s' % ticket.get_status_display()

    if not f.title:
        if f.comment:
            f.title = _('Comment')
        else:
            f.title = _('Updated')

    f.save()

    files = process_attachments(f, request.FILES.getlist('attachment'))

    if title and title != ticket.title:
        c = TicketChange(
            followup=f,
            field=_('Title'),
            old_value=ticket.title,
            new_value=title,
        )
        c.save()
        ticket.title = title

    if new_status != old_status:
        c = TicketChange(
            followup=f,
            field=_('Status'),
            old_value=old_status_str,
            new_value=ticket.get_status_display(),
        )
        c.save()

    if ticket.assigned_to != old_owner:
        c = TicketChange(
            followup=f,
            field=_('Owner'),
            old_value=old_owner,
            new_value=ticket.assigned_to,
        )
        c.save()

    if priority != ticket.priority:
        c = TicketChange(
            followup=f,
            field=_('Priority'),
            old_value=ticket.priority,
            new_value=priority,
        )
        c.save()
        ticket.priority = priority

    if due_date != old_due_date:
        c = TicketChange(
            followup=f,
            field=_('Due on'),
            old_value=old_due_date,
            new_value=due_date,
        )
        c.save()
        ticket.due_date = due_date

    if new_status in (Ticket.RESOLVED_STATUS, Ticket.CLOSED_STATUS):
        if new_status == Ticket.RESOLVED_STATUS or ticket.resolution is None:
            ticket.resolution = comment

    messages_sent_to = []

    # ticket might have changed above, so we re-instantiate context with the
    # (possibly) updated ticket.
    context = safe_template_context(ticket)
    context.update(
        resolution=ticket.resolution,
        comment=f.comment,
    )

    if public and (f.comment or (
        f.new_status in (Ticket.RESOLVED_STATUS,
                         Ticket.CLOSED_STATUS))):
        if f.new_status == Ticket.RESOLVED_STATUS:
            template = 'resolved_'
        elif f.new_status == Ticket.CLOSED_STATUS:
            template = 'closed_'
        else:
            template = 'updated_'

        template_suffix = 'submitter'

        if ticket.submitter_email:
            send_templated_mail(
                template + template_suffix,
                context,
                recipients=ticket.submitter_email,
                sender=ticket.queue.from_address,
                fail_silently=True,
                files=files,
            )
            messages_sent_to.append(ticket.submitter_email)

        template_suffix = 'cc'

        for cc in ticket.ticketcc_set.all():
            if cc.email_address not in messages_sent_to:
                send_templated_mail(
                    template + template_suffix,
                    context,
                    recipients=cc.email_address,
                    sender=ticket.queue.from_address,
                    fail_silently=True,
                    files=files,
                )
                messages_sent_to.append(cc.email_address)

    if ticket.assigned_to and \
            request.user != ticket.assigned_to and \
            ticket.assigned_to.email and \
            ticket.assigned_to.email not in messages_sent_to:
        # We only send e-mails to staff members if the ticket is updated by
        # another user. The actual template varies, depending on what has been
        # changed.
        if reassigned:
            template_staff = 'assigned_owner'
        elif f.new_status == Ticket.RESOLVED_STATUS:
            template_staff = 'resolved_owner'
        elif f.new_status == Ticket.CLOSED_STATUS:
            template_staff = 'closed_owner'
        else:
            template_staff = 'updated_owner'

        if (not reassigned or
                (reassigned and
                    ticket.assigned_to.usersettings_helpdesk.settings.get(
                        'email_on_ticket_assign', False))) or \
            (not reassigned and
                ticket.assigned_to.usersettings_helpdesk.settings.get(
                    'email_on_ticket_change', False)):
            send_templated_mail(
                template_staff,
                context,
                recipients=ticket.assigned_to.email,
                sender=ticket.queue.from_address,
                fail_silently=True,
                files=files,
            )
            messages_sent_to.append(ticket.assigned_to.email)

    if ticket.queue.updated_ticket_cc and ticket.queue.updated_ticket_cc not in messages_sent_to:
        if reassigned:
            template_cc = 'assigned_cc'
        elif f.new_status == Ticket.RESOLVED_STATUS:
            template_cc = 'resolved_cc'
        elif f.new_status == Ticket.CLOSED_STATUS:
            template_cc = 'closed_cc'
        else:
            template_cc = 'updated_cc'

        send_templated_mail(
            template_cc,
            context,
            recipients=ticket.queue.updated_ticket_cc,
            sender=ticket.queue.from_address,
            fail_silently=True,
            files=files,
        )

    ticket.save()
    if new_status != old_status:
        try:
            ticket.send_notifications()
        except Exception:
            traceback.print_exc()

    # auto subscribe user if enabled
    if helpdesk_settings.HELPDESK_AUTO_SUBSCRIBE_ON_TICKET_RESPONSE and request.user.is_authenticated():
        ticketcc_string, SHOW_SUBSCRIBE = return_ticketccstring_and_show_subscribe(request.user, ticket)
        if SHOW_SUBSCRIBE:
            subscribe_staff_member_to_ticket(ticket, request.user)

    return return_to_ticket(request.user, helpdesk_settings, ticket)


def return_to_ticket(user, helpdesk_settings, ticket):
    """Helper function for update_ticket"""

    if user.is_staff or helpdesk_settings.HELPDESK_ALLOW_NON_STAFF_TICKET_UPDATE:
        return HttpResponseRedirect(ticket.get_absolute_url())
    else:
        return HttpResponseRedirect(ticket.ticket_url)


def edit_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    if request.method == 'POST':
        form = EditTicketForm(request.POST, instance=ticket)
        if form.is_valid():
            ticket = form.save()
            return HttpResponseRedirect(ticket.get_absolute_url())
    else:
        form = EditTicketForm(instance=ticket)

    return render(request, 'helpdesk/edit_ticket.html', {'form': form})
edit_ticket = staff_member_required(edit_ticket)


def create_ticket(request):
    if helpdesk_settings.HELPDESK_STAFF_ONLY_TICKET_OWNERS:
        assignable_users = User.objects.filter(is_active=True, is_staff=True).order_by(User.USERNAME_FIELD)
    else:
        assignable_users = User.objects.filter(is_active=True).order_by(User.USERNAME_FIELD)

    if request.method == 'POST':
        form = TicketForm(request.POST, request.FILES)
        form.fields['assigned_to'].queryset = assignable_users
        if form.is_valid():
            ticket = form.save(user=request.user)
            if _has_access_to_queue(request.user, ticket.queue):
                return HttpResponseRedirect(ticket.get_absolute_url())
            else:
                return HttpResponseRedirect(reverse('helpdesk:dashboard'))
    else:
        initial_data = {}
        if request.user.usersettings_helpdesk.settings.get('use_email_as_submitter', False) and request.user.email:
            initial_data['submitter_email'] = request.user.email
        if 'queue' in request.GET:
            initial_data['queue'] = request.GET['queue']

        form = TicketForm(initial=initial_data)
        form.fields['assigned_to'].queryset = assignable_users
        if helpdesk_settings.HELPDESK_CREATE_TICKET_HIDE_ASSIGNED_TO:
            form.fields['assigned_to'].widget = forms.HiddenInput()

    return render(request, 'helpdesk/create_ticket.html', {'form': form})
create_ticket = staff_member_required(create_ticket)


def raw_details(request, type):
    # TODO: This currently only supports spewing out 'PreSetReply' objects,
    # in the future it needs to be expanded to include other items. All it
    # does is return a plain-text representation of an object.

    if type not in ('preset',):
        raise Http404

    if type == 'preset' and request.GET.get('id', False):
        try:
            preset = PreSetReply.objects.get(id=request.GET.get('id'))
            return HttpResponse(preset.body)
        except PreSetReply.DoesNotExist:
            raise Http404

    raise Http404
raw_details = staff_member_required(raw_details)


def rss_list(request):
    return render(request, 'helpdesk/rss_list.html', {'queues': Queue.objects.all()})
rss_list = staff_member_required(rss_list)


def stat_index(request):
    number_tickets = Ticket.objects.all().count()
    saved_query = request.GET.get('saved_query', None)

    user_queues = _get_user_queues(request.user)
    Tickets = Ticket.objects.filter(queue__in=user_queues)
    basic_ticket_stats = calc_basic_ticket_stats(Tickets)

    # The following query builds a grid of queues & ticket statuses,
    # to be displayed to the user. EG:
    #          Open  Resolved
    # Queue 1    10     4
    # Queue 2     4    12

    queues = _get_user_queues(request.user).values_list('id', flat=True)

    from_clause = """FROM    helpdesk_ticket t,
                    helpdesk_queue q"""
    if queues:
        where_clause = """WHERE   q.id = t.queue_id AND
                        q.id IN (%s)""" % (",".join(("%d" % pk for pk in queues)))
    else:
        where_clause = """WHERE   q.id = t.queue_id"""

    cursor = connection.cursor()
    cursor.execute("""
        SELECT      q.id as queue,
                    q.title AS name,
                    COUNT(CASE t.status WHEN '1' THEN t.id WHEN '2' THEN t.id END) AS open,
                    COUNT(CASE t.status WHEN '3' THEN t.id END) AS resolved,
                    COUNT(CASE t.status WHEN '4' THEN t.id END) AS closed
            %s
            %s
            GROUP BY queue, name
            ORDER BY q.id;
    """ % (from_clause, where_clause))

    dash_tickets = query_to_dict(cursor.fetchall(), cursor.description)

    return render(request, 'helpdesk/stat_index.html', {
        'number_tickets': number_tickets,
        'saved_query': saved_query,
        'basic_ticket_stats': basic_ticket_stats,
        'dash_tickets': dash_tickets,
    })
stat_index = staff_member_required(stat_index)


def run_stat(request, report):
    if Ticket.objects.all().count() == 0 or report not in (
            'queuemonth', 'usermonth', 'queuestatus', 'queuepriority', 'userstatus',
            'userpriority', 'userqueue', 'daysuntilticketclosedbymonth'):
        return HttpResponseRedirect(reverse("helpdesk:stat_index"))

    report_queryset = Ticket.objects.all().select_related().filter(
        queue__in=_get_user_queues(request.user)
    )

    from_saved_query = False
    saved_query = None

    if request.GET.get('saved_query', None):
        from_saved_query = True
        try:
            saved_query = SavedSearch.objects.get(pk=request.GET.get('saved_query'))
        except SavedSearch.DoesNotExist:
            return HttpResponseRedirect(reverse('helpdesk:stat_index'))
        if not (saved_query.shared or saved_query.user == request.user):
            return HttpResponseRedirect(reverse('helpdesk:stat_index'))

        import json
        from helpdesk.lib import b64decode
        try:
            query_params = json.loads(b64decode(str(saved_query.query)).decode())
        except:
            return HttpResponseRedirect(reverse('helpdesk:stat_index'))

        report_queryset = apply_query(report_queryset, query_params)

    from collections import defaultdict
    summarytable = defaultdict(int)
    # a second table for more complex queries
    summarytable2 = defaultdict(int)

    def month_name(m):
        MONTHS_3[m].title()

    first_ticket = Ticket.objects.all().order_by('created')[0]
    first_month = first_ticket.created.month
    first_year = first_ticket.created.year

    last_ticket = Ticket.objects.all().order_by('-created')[0]
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

    if report == 'userpriority':
        title = _('User by Priority')
        col1heading = _('User')
        possible_options = [t[1].title() for t in Ticket.PRIORITY_CHOICES]
        charttype = 'bar'

    elif report == 'userqueue':
        title = _('User by Queue')
        col1heading = _('User')
        queue_options = _get_user_queues(request.user)
        possible_options = [q.title for q in queue_options]
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
    })
run_stat = staff_member_required(run_stat)


def user_settings(request):
    s = request.user.usersettings_helpdesk
    user_saved_query = SavedSearch.objects.filter(Q(user=request.user) | Q(shared__exact=True))
    if request.POST:
        form = UserSettingsForm(request.POST)
        form.fields['default_ticket_saved_query'].queryset = user_saved_query
        if form.is_valid():
            s.settings = form.cleaned_data
            s.save()
    else:
        form = UserSettingsForm(s.settings)
        form.fields['default_ticket_saved_query'].queryset = user_saved_query

    return render(request, 'helpdesk/user_settings.html', {'form': form})
user_settings = staff_member_required(user_settings)


def email_ignore(request):
    return render(request, 'helpdesk/email_ignore_list.html', {
        'ignore_list': IgnoreEmail.objects.all(),
    })
email_ignore = superuser_required(email_ignore)


def email_ignore_add(request):
    if request.method == 'POST':
        form = EmailIgnoreForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('helpdesk:email_ignore'))
    else:
        form = EmailIgnoreForm(request.GET)

    return render(request, 'helpdesk/email_ignore_add.html', {'form': form})
email_ignore_add = superuser_required(email_ignore_add)


def email_ignore_del(request, id):
    ignore = get_object_or_404(IgnoreEmail, id=id)
    if request.method == 'POST':
        ignore.delete()
        return HttpResponseRedirect(reverse('helpdesk:email_ignore'))
    else:
        return render(request, 'helpdesk/email_ignore_del.html', {'ignore': ignore})
email_ignore_del = superuser_required(email_ignore_del)


def ticket_cc(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    copies_to = ticket.ticketcc_set.all()
    return render(request, 'helpdesk/ticket_cc_list.html', {
        'copies_to': copies_to,
        'ticket': ticket,
    })
ticket_cc = staff_member_required(ticket_cc)


def ticket_cc_add(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    if request.method == 'POST':
        form = TicketCCForm(request.POST)
        if form.is_valid():
            ticketcc = form.save(commit=False)
            ticketcc.ticket = ticket
            ticketcc.save()
            return HttpResponseRedirect(reverse('helpdesk:ticket_cc',
                                                kwargs={'ticket_id': ticket.id}))
    else:
        form_email = TicketCCEmailForm()
        form_user = TicketCCUserForm()
    return render(request, 'helpdesk/ticket_cc_add.html', {
        'ticket': ticket,
        'form_email': form_email,
        'form_user': form_user,
    })
ticket_cc_add = staff_member_required(ticket_cc_add)


def ticket_cc_del(request, ticket_id, cc_id):
    cc = get_object_or_404(TicketCC, ticket__id=ticket_id, id=cc_id)

    if request.method == 'POST':
        cc.delete()
        return HttpResponseRedirect(reverse('helpdesk:ticket_cc',
                                            kwargs={'ticket_id': cc.ticket.id}))
    return render(request, 'helpdesk/ticket_cc_del.html', {'cc': cc})
ticket_cc_del = staff_member_required(ticket_cc_del)


def ticket_dependency_add(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()
    if request.method == 'POST':
        form = TicketDependencyForm(request.POST)
        if form.is_valid():
            ticketdependency = form.save(commit=False)
            ticketdependency.ticket = ticket
            if ticketdependency.ticket != ticketdependency.depends_on:
                ticketdependency.save()
            return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket.id]))
    else:
        form = TicketDependencyForm()
    return render(request, 'helpdesk/ticket_dependency_add.html', {
        'ticket': ticket,
        'form': form,
    })
ticket_dependency_add = staff_member_required(ticket_dependency_add)


def ticket_dependency_del(request, ticket_id, dependency_id):
    dependency = get_object_or_404(TicketDependency, ticket__id=ticket_id, id=dependency_id)
    if request.method == 'POST':
        dependency.delete()
        return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket_id]))
    return render(request, 'helpdesk/ticket_dependency_del.html', {'dependency': dependency})
ticket_dependency_del = staff_member_required(ticket_dependency_del)


def attachment_del(request, ticket_id, attachment_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    if not _has_access_to_queue(request.user, ticket.queue):
        raise PermissionDenied()

    attachment = get_object_or_404(Attachment, id=attachment_id)
    if request.method == 'POST':
        attachment.delete()
        return HttpResponseRedirect(reverse('helpdesk:view', args=[ticket_id]))
    return render(request, 'helpdesk/ticket_attachment_del.html', {
        'attachment': attachment,
        'filename': attachment.filename,
    })
attachment_del = staff_member_required(attachment_del)


def calc_average_nbr_days_until_ticket_resolved(Tickets):
    nbr_closed_tickets = len(Tickets)
    days_per_ticket = 0
    days_each_ticket = list()

    for ticket in Tickets:
        time_ticket_open = ticket.modified - ticket.created
        days_this_ticket = time_ticket_open.days
        days_per_ticket += days_this_ticket
        days_each_ticket.append(days_this_ticket)

    if nbr_closed_tickets > 0:
        mean_per_ticket = days_per_ticket / nbr_closed_tickets
    else:
        mean_per_ticket = 0

    return mean_per_ticket


def calc_basic_ticket_stats(Tickets):
    # all not closed tickets (open, reopened, resolved) - independent of user
    all_open_tickets = Tickets.filter(
        status__in=[Ticket.OPEN_STATUS, Ticket.REOPENED_STATUS, Ticket.RESOLVED_STATUS])
    today = datetime.today()

    date_30 = date_rel_to_today(today, 30)
    date_60 = date_rel_to_today(today, 60)
    date_30_str = date_30.strftime('%Y-%m-%d')
    date_60_str = date_60.strftime('%Y-%m-%d')

    # > 0 & <= 30
    ota_le_30 = all_open_tickets.filter(created__gte=date_30_str)
    N_ota_le_30 = len(ota_le_30)

    # >= 30 & <= 60
    ota_le_60_ge_30 = all_open_tickets.filter(created__gte=date_60_str, created__lte=date_30_str)
    N_ota_le_60_ge_30 = len(ota_le_60_ge_30)

    # >= 60
    ota_ge_60 = all_open_tickets.filter(created__lte=date_60_str)
    N_ota_ge_60 = len(ota_ge_60)

    # (O)pen (T)icket (S)tats
    ots = list()
    # label, number entries, color, sort_string
    ots.append(['Tickets < 30 days', N_ota_le_30, 'success',
                sort_string(date_30_str, ''), ])
    ots.append(['Tickets 30 - 60 days', N_ota_le_60_ge_30,
                'success' if N_ota_le_60_ge_30 == 0 else 'warning',
                sort_string(date_60_str, date_30_str), ])
    ots.append(['Tickets > 60 days', N_ota_ge_60,
                'success' if N_ota_ge_60 == 0 else 'danger',
                sort_string('', date_60_str), ])

    # all closed tickets - independent of user.
    all_closed_tickets = Tickets.filter(status=Ticket.CLOSED_STATUS)
    average_nbr_days_until_ticket_closed = \
        calc_average_nbr_days_until_ticket_resolved(all_closed_tickets)
    # all closed tickets that were opened in the last 60 days.
    all_closed_last_60_days = all_closed_tickets.filter(created__gte=date_60_str)
    average_nbr_days_until_ticket_closed_last_60_days = \
        calc_average_nbr_days_until_ticket_resolved(all_closed_last_60_days)

    # put together basic stats
    basic_ticket_stats = {
        'average_nbr_days_until_ticket_closed': average_nbr_days_until_ticket_closed,
        'average_nbr_days_until_ticket_closed_last_60_days':
            average_nbr_days_until_ticket_closed_last_60_days,
        'open_ticket_stats': ots,
    }

    return basic_ticket_stats


def get_color_for_nbr_days(nbr_days):
    if nbr_days < 5:
        color_string = 'green'
    elif nbr_days < 10:
        color_string = 'orange'
    else:  # more than 10 days
        color_string = 'red'

    return color_string


def days_since_created(today, ticket):
    return (today - ticket.created).days


def date_rel_to_today(today, offset):
    return today - timedelta(days=offset)


def sort_string(begin, end):
    return 'order_by=created&created_min=%s&created_max=%s&status=%s&status=%s&status=%s' % (
        begin, end, Ticket.OPEN_STATUS, Ticket.REOPENED_STATUS, Ticket.RESOLVED_STATUS)


@method_decorator(staff_member_required, name='dispatch')
class AddTicketTimeTrackView(CreateView):
    template_name = "helpdesk/ticket_time_track_add.html"
    model = TicketTimeTrack
    form_class = TicketTimeTrackForm
    pk_url_kwarg = 'ticket_id'
    _ticket = None

    def get_form(self, form_class=None):
        form = super(AddTicketTimeTrackView, self).get_form(form_class=form_class)
        form.instance.tracked_by = self.request.user
        form.instance.ticket = self.get_ticket()
        return form

    def get_context_data(self, **kwargs):
        ctx = super(AddTicketTimeTrackView, self).get_context_data(**kwargs)
        ctx['ticket'] = self.get_ticket()
        return ctx

    def get_ticket(self):
        if not self._ticket:
            ticket_id = self.kwargs.get(self.pk_url_kwarg)
            self._ticket = get_object_or_404(Ticket, id=ticket_id)
        return self._ticket

    def form_valid(self, form):
        now = timezone.now()
        if form.instance.tracked_at > now:
            form.instance.tracked_at = now
        result = super(AddTicketTimeTrackView, self).form_valid(form)
        messages.success(self.request, '"{}" time added to "{}" successfully.'.format(form.instance,
                                                                                      form.instance.ticket))
        return result

    def get_success_url(self):
        return self.get_ticket().get_absolute_url()


def _has_access_change_track_Time(user, track_time):
    return (user == track_time.tracked_by) or user.has_perm('helpdesk.change_others_tickettimetrack')


def _has_access_delete_track_Time(user, track_time):
    return (user == track_time.tracked_by) or user.has_perm('helpdesk.delete_others_tickettimetrack')


@method_decorator(staff_member_required, name='dispatch')
class UpdateTicketTimeTrackView(UpdateView):
    pk_url_kwarg = 'pk'
    template_name = "helpdesk/ticket_time_track_edit.html"
    model = TicketTimeTrack
    form_class = TicketTimeTrackForm

    def get_object(self, queryset=None):
        object = super(UpdateTicketTimeTrackView, self).get_object(queryset=queryset)
        if not _has_access_change_track_Time(self.request.user, object):
            raise PermissionDenied()
        return object

    def form_valid(self, form):
        now = timezone.now()
        if form.instance.tracked_at > now:
            form.instance.tracked_at = now
        result = super(UpdateTicketTimeTrackView, self).form_valid(form)
        messages.success(self.request, 'a time of ticket "{}" updated successfully.'.format(form.instance.ticket))
        return result

    def get_success_url(self):
        return self.object.ticket.get_absolute_url()


@method_decorator(staff_member_required, name='dispatch')
class DeleteTicketTimeTrackView(DeleteView):
    model = TicketTimeTrack
    template_name = 'helpdesk/ticket_time_track_confirm_delete.html'

    def get_object(self, queryset=None):
        object = super(DeleteTicketTimeTrackView, self).get_object(queryset=queryset)
        if not _has_access_delete_track_Time(self.request.user, object):
            raise PermissionDenied()
        return object

    def delete(self, request, *args, **kwargs):
        res = super(DeleteTicketTimeTrackView, self).delete(request, *args, **kwargs)
        messages.success(self.request, '"{}" time deleted from "{}" successfully.'.format(self.object, self.object.ticket))
        return res
    def get_success_url(self):
        return self.object.ticket.get_absolute_url()


@method_decorator(staff_member_required, name='dispatch')
class AddTicketMoneyTrackView(CreateView):
    template_name = "helpdesk/ticket_money_track_add.html"
    model = TicketMoneyTrack
    form_class = TicketMoneyTrackForm
    pk_url_kwarg = 'ticket_id'
    _ticket = None

    def get_form(self, form_class=None):
        form = super(AddTicketMoneyTrackView, self).get_form(form_class=form_class)
        form.instance.tracked_by = self.request.user
        form.instance.ticket = self.get_ticket()
        return form

    def get_context_data(self, **kwargs):
        ctx = super(AddTicketMoneyTrackView, self).get_context_data(**kwargs)
        ctx['ticket'] = self.get_ticket()
        return ctx

    def get_ticket(self):
        if not self._ticket:
            ticket_id = self.kwargs.get(self.pk_url_kwarg)
            self._ticket = get_object_or_404(Ticket, id=ticket_id)
        return self._ticket

    def form_valid(self, form):
        now = timezone.now()
        if form.instance.tracked_at > now:
            form.instance.tracked_at = now
        result = super(AddTicketMoneyTrackView, self).form_valid(form)
        messages.success(self.request, '"${}" money added to "{}" successfully.'.format(form.instance,
                                                                                        form.instance.ticket))
        return result

    def get_success_url(self):
        return self.get_ticket().get_absolute_url()


def _has_access_change_track_Money(user, track_money):
    return (user == track_money.tracked_by) or user.has_perm('helpdesk.change_others_ticketmoneytrack')


def _has_access_delete_track_Money(user, track_money):
    return (user == track_money.tracked_by) or user.has_perm('helpdesk.delete_others_ticketmoneytrack')


@method_decorator(staff_member_required, name='dispatch')
class UpdateTicketMoneyTrackView(UpdateView):
    pk_url_kwarg = 'pk'
    template_name = "helpdesk/ticket_money_track_edit.html"
    model = TicketMoneyTrack
    form_class = TicketMoneyTrackForm

    def get_object(self, queryset=None):
        object = super(UpdateTicketMoneyTrackView, self).get_object(queryset=queryset)
        if not _has_access_change_track_Money(self.request.user, object):
            raise PermissionDenied()
        return object

    def form_valid(self, form):
        now = timezone.now()
        if form.instance.tracked_at > now:
            form.instance.tracked_at = now
        result = super(UpdateTicketMoneyTrackView, self).form_valid(form)
        messages.success(self.request, 'a money of ticket "{}" updated successfully.'.format(form.instance.ticket))
        return result

    def get_success_url(self):
        return self.object.ticket.get_absolute_url()


@method_decorator(staff_member_required, name='dispatch')
class DeleteTicketMoneyTrackView(DeleteView):
    model = TicketMoneyTrack
    template_name = 'helpdesk/ticket_money_track_confirm_delete.html'

    def get_object(self, queryset=None):
        object = super(DeleteTicketMoneyTrackView, self).get_object(queryset=queryset)
        if not _has_access_delete_track_Money(self.request.user, object):
            raise PermissionDenied()
        return object

    def delete(self, request, *args, **kwargs):
        res = super(DeleteTicketMoneyTrackView, self).delete(request, *args, **kwargs)
        messages.success(self.request, '"${}" money deleted from "{}" successfully.'.format(self.object, self.object.ticket))
        return res
    def get_success_url(self):
        return self.object.ticket.get_absolute_url()

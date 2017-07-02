from django import forms
from django.contrib import admin
from django.utils.translation import ugettext_lazy as _
from helpdesk.models import Queue, Ticket, FollowUp, PreSetReply, KBCategory, TicketTimeTrack, TicketMoneyTrack, \
    SMSTemplate, TicketNotification
from helpdesk.models import EscalationExclusion, EmailTemplate, KBItem
from helpdesk.models import TicketChange, Attachment, IgnoreEmail
from helpdesk.models import CustomField


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'email_address', 'locale')
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'assigned_to', 'queue', 'hidden_submitter_email',)
    date_hierarchy = 'created'
    list_filter = ('queue', 'assigned_to', 'status')

    def hidden_submitter_email(self, ticket):
        if ticket.submitter_email:
            username, domain = ticket.submitter_email.split("@")
            username = username[:2] + "*" * (len(username) - 2)
            domain = domain[:1] + "*" * (len(domain) - 2) + domain[-1:]
            return "%s@%s" % (username, domain)
        else:
            return ticket.submitter_email
    hidden_submitter_email.short_description = _('Submitter E-Mail')


class TicketChangeInline(admin.StackedInline):
    model = TicketChange


class AttachmentInline(admin.StackedInline):
    model = Attachment


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    inlines = [TicketChangeInline, AttachmentInline]
    list_display = ('ticket_get_ticket_for_url', 'title', 'date', 'ticket', 'user', 'new_status')
    list_filter = ('user', 'date', 'new_status')

    def ticket_get_ticket_for_url(self, obj):
        return obj.ticket.ticket_for_url
    ticket_get_ticket_for_url.short_description = _('Slug')


@admin.register(KBItem)
class KBItemAdmin(admin.ModelAdmin):
    list_display = ('category', 'title', 'last_updated',)
    list_display_links = ('title',)


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ('name', 'label', 'data_type')


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('template_name', 'heading', 'locale')
    list_filter = ('locale', )


@admin.register(TicketTimeTrack)
class TicketTimeTrackAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'time', 'tracked_at', 'tracked_by')


@admin.register(TicketMoneyTrack)
class TicketMoneyTrackAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'money', 'tracked_at', 'tracked_by')


@admin.register(IgnoreEmail)
class IgnoreEmailAdmin(admin.ModelAdmin):
    list_display = ('name', 'queue_list', 'email_address', 'keep_in_mailbox')


@admin.register(SMSTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('template_name', 'locale')
    list_filter = ('locale', )


class TicketNotificationForm(forms.ModelForm):
    statuses = forms.MultipleChoiceField(
        label='When status changed to', choices=Ticket.STATUS_CHOICES, required=False,
        help_text=_('Leave blank to be ignored on all statuses, or select those statuses wish to be notified.'))
    priorities = forms.MultipleChoiceField(
        label='When priorities are', choices=Ticket.PRIORITY_CHOICES, required=False,
        help_text=_('Leave blank to be ignored on all priorities, or select those priorities wish to be notified.'))
    def clean_statuses(self):
        statuses = self.cleaned_data['statuses']
        statuses = ','.join(statuses)
        return '{},'.format(statuses) if statuses else statuses

    def clean_priorities(self):
        priorities = self.cleaned_data['priorities']
        priorities = ','.join(priorities)
        return '{},'.format(priorities) if priorities else priorities

    class Meta:
        model = TicketNotification
        exclude = []
        labels = {
            'queues': _('When Queues are'),
            'to': _('To E-Mail Address or SMS Number')
        }


@admin.register(TicketNotification)
class TicketNotificationAdmin(admin.ModelAdmin):
    list_display = ('notify_type', 'to', 'priorities_display', 'statuses_display', 'queues_display')
    list_filter = ('notify_type', )
    form = TicketNotificationForm

    def priorities_display(self, obj):
        return obj.priorities_display
    priorities_display.short_description = _('Priorities')

    def statuses_display(self, obj):
        return obj.statuses_display
    statuses_display.short_description = _('Statuses')

    def queues_display(self, obj):
        return obj.queues_display
    queues_display.short_description = _('Queues')


admin.site.register(PreSetReply)
admin.site.register(EscalationExclusion)
admin.site.register(KBCategory)

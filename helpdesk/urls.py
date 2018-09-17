"""
django-helpdesk - A Django powered ticket tracker for small enterprise.

(c) Copyright 2008 Jutda. All Rights Reserved. See LICENSE for details.

urls.py - Mapping of URL's to our various views. Note we always used NAMED
          views for simplicity in linking later on.
"""

from django.conf.urls import url
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView

from helpdesk import settings as helpdesk_settings
from helpdesk.views import feeds, staff, public, kb
from helpdesk.views import staff2


class DirectTemplateView(TemplateView):
    extra_context = None

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)
        if self.extra_context is not None:
            for key, value in self.extra_context.items():
                if callable(value):
                    context[key] = value()
                else:
                    context[key] = value
        return context

app_name = 'helpdesk'

urlpatterns = [
    url(r'^dashboard/$',
        staff.dashboard,
        name='dashboard'),

    url(r'^tickets/submit/$',
        staff.create_ticket,
        name='submit'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/$',
        staff.view_ticket,
        name='view'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/followup_edit/(?P<followup_id>[0-9]+)/$',
        staff.followup_edit,
        name='followup_edit'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/followup_delete/(?P<followup_id>[0-9]+)/$',
        staff.followup_delete,
        name='followup_delete'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/edit/$',
        staff.edit_ticket,
        name='edit'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/update/$',
        staff.update_ticket,
        name='update'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/delete/$',
        staff.delete_ticket,
        name='delete'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/cc/$',
        staff.ticket_cc,
        name='ticket_cc'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/cc/add/$',
        staff.ticket_cc_add,
        name='ticket_cc_add'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/cc/delete/(?P<cc_id>[0-9]+)/$',
        staff.ticket_cc_del,
        name='ticket_cc_del'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/dependency/add/$',
        staff.ticket_dependency_add,
        name='ticket_dependency_add'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/dependency/delete/(?P<dependency_id>[0-9]+)/$',
        staff.ticket_dependency_del,
        name='ticket_dependency_del'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/attachment_delete/(?P<attachment_id>[0-9]+)/$',
        staff.attachment_del,
        name='attachment_del'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/time_track/add/$',
        staff.AddTicketTimeTrackView.as_view(),
        name='ticket_time_track_add'),

    url(r'^tickets/time_track/edit/(?P<pk>[0-9]+)/$',
        staff.UpdateTicketTimeTrackView.as_view(),
        name='ticket_time_track_edit'),

    url(r'^tickets/time_track/delete/(?P<pk>[0-9]+)/$',
        staff.DeleteTicketTimeTrackView.as_view(),
        name='ticket_time_track_delete'),

    url(r'^tickets/(?P<ticket_id>[0-9]+)/money_track/add/$',
        staff.AddTicketMoneyTrackView.as_view(),
        name='ticket_money_track_add'),

    url(r'^tickets/money_track/edit/(?P<pk>[0-9]+)/$',
        staff.UpdateTicketMoneyTrackView.as_view(),
        name='ticket_money_track_edit'),

    url(r'^tickets/money_track/delete/(?P<pk>[0-9]+)/$',
        staff.DeleteTicketMoneyTrackView.as_view(),
        name='ticket_money_track_delete'),

    url(r'^raw/(?P<type>\w+)/$',
        staff.raw_details,
        name='raw'),

    url(r'^rss/$',
        staff.rss_list,
        name='rss_index'),

    url(r'^stats/$',
        staff.stat_index,
        name='stat_index'),

    url(r'^reports/(?P<report>\w+)/$',
        staff2.RunStatView.as_view(),
        name='run_stat'),

    url(r'^settings/$',
        staff.user_settings,
        name='user_settings'),

    url(r'^ignore/$',
        staff.email_ignore,
        name='email_ignore'),

    url(r'^ignore/add/$',
        staff.email_ignore_add,
        name='email_ignore_add'),

    url(r'^ignore/delete/(?P<id>[0-9]+)/$',
        staff.email_ignore_del,
        name='email_ignore_del'),
]

urlpatterns += [
    url(r'^ticket/list/$', staff2.TicketListView.as_view(), name='ticket-list'),
    url(r'^ticket/delete/(?P<pk>\d+)/$', staff2.TicketDeleteView.as_view(), name='ticket-delete'),
    url(r'^ticket/take/(?P<pk>\d+)/$', staff2.TicketTakeView.as_view(), name='ticket-take'),
    url(r'^ticket/delete/bulk/(?P<pk>((\d+),?)+)/$', staff2.TicketsBulkDeleteView.as_view(),
        name='tickets-bulk-delete'),
    url(r'^ticket/close/bulk/(?P<pk>((\d+),?)+)/$', staff2.TicketsBulkCloseView.as_view(), name='tickets-bulk-close'),
    url(r'^ticket/assign/bulk/(?P<pk>((\d+),?)+)/$', staff2.TicketsBulkAssignView.as_view(),
        name='tickets-bulk-assign'),
    url(r'^saved_search/list/$', staff2.SavedSearchListView.as_view(), name='saved_search-list'),
    url(r'^saved_search/add/$', staff2.SavedSearchAddView.as_view(), name='saved_search-add'),
    url(r'^saved_search/delete/(?P<pk>\d+)/$', staff2.SavedSearchDeleteView.as_view(), name='saved_search-delete'),
    url(r'^saved_search/switch-shared/(?P<pk>\d+)/$', staff2.SavedSearchSwitchSharedView.as_view(),
        name='saved_search-switch-shared'),
    url(r'^saved_search/default/(?P<pk>\d+)/$', staff2.SavedSearchSetDefaultView.as_view(),
        name='saved_search-set-default'),
    url(r'^report/custom-date/$', staff2.CustomDateReportView.as_view(), name='report-custom-date'),
    url(r'^queue/list/$', staff2.QueueListView.as_view(), name='queue-list'),
    url(r'^queue/add/$', staff2.QueueAddView.as_view(), name='queue-add'),
    url(r'^queue/edit/(?P<pk>\d+)/$', staff2.QueueEditView.as_view(), name='queue-edit'),
    url(r'^queue/delete/(?P<pk>\d+)/$', staff2.QueueDeleteView.as_view(), name='queue-delete'),
    url(r'^ticket-notification/list/$', staff2.TicketNotificationListView.as_view(), name='ticket_notification-list'),
    url(r'^ticket-notification/add/$', staff2.TicketNotificationAddView.as_view(), name='ticket_notification-add'),
    url(r'^ticket-notification/edit/(?P<pk>\d+)/$', staff2.TicketNotificationEditView.as_view(),
        name='ticket_notification-edit'),
    url(r'^ticket-notification/delete/(?P<pk>\d+)/$', staff2.TicketNotificationDeleteView.as_view(),
        name='ticket_notification-delete'),
    url(r'^email-template/list/$', staff2.EmailTemplateListView.as_view(), name='email_template-list'),
    url(r'^email-template/add/$', staff2.EmailTemplateAddView.as_view(), name='email_template-add'),
    url(r'^email-template/edit/(?P<pk>\d+)/$', staff2.EmailTemplateEditView.as_view(),
        name='email_template-edit'),
    url(r'^email-template/delete/(?P<pk>\d+)/$', staff2.EmailTemplateDeleteView.as_view(),
        name='email_template-delete'),
    url(r'^sms-template/list/$', staff2.SMSTemplateListView.as_view(), name='sms_template-list'),
    url(r'^sms-template/add/$', staff2.SMSTemplateAddView.as_view(), name='sms_template-add'),
    url(r'^sms-template/edit/(?P<pk>\d+)/$', staff2.SMSTemplateEditView.as_view(),
        name='sms_template-edit'),
    url(r'^sms-template/delete/(?P<pk>\d+)/$', staff2.SMSTemplateDeleteView.as_view(),
        name='sms_template-delete'),
]

urlpatterns += [
    url(r'^$',
        public.homepage,
        name='home'),

    url(r'^view/$',
        public.view_ticket if helpdesk_settings.HELPDESK_VIEW_A_TICKET_PUBLIC else login_required(public.view_ticket),
        name='public_view'),

    url(r'^change_language/$',
        public.change_language,
        name='public_change_language'),
]

urlpatterns += [
    url(r'^rss/user/(?P<user_name>[^/]+)/$',
        login_required(feeds.OpenTicketsByUser()),
        name='rss_user'),

    url(r'^rss/user/(?P<user_name>[^/]+)/(?P<queue_slug>[A-Za-z0-9_-]+)/$',
        login_required(feeds.OpenTicketsByUser()),
        name='rss_user_queue'),

    url(r'^rss/queue/(?P<queue_slug>[A-Za-z0-9_-]+)/$',
        login_required(feeds.OpenTicketsByQueue()),
        name='rss_queue'),

    url(r'^rss/unassigned/$',
        login_required(feeds.UnassignedTickets()),
        name='rss_unassigned'),

    url(r'^rss/recent_activity/$',
        login_required(feeds.RecentFollowUps()),
        name='rss_activity'),
]


urlpatterns += [
    url(r'^login/$',
        auth_views.login,
        {'template_name': 'helpdesk/registration/login.html'},
        name='login'),

    url(r'^logout/$',
        auth_views.logout,
        {'template_name': 'helpdesk/registration/login.html', 'next_page': '../'},
        name='logout'),
]

if helpdesk_settings.HELPDESK_KB_ENABLED:
    urlpatterns += [
        url(r'^kb/$',
            kb.index,
            name='kb_index'),

        url(r'^kb/(?P<item>[0-9]+)/$',
            kb.item,
            name='kb_item'),

        url(r'^kb/(?P<item>[0-9]+)/vote/$',
            kb.vote,
            name='kb_vote'),

        url(r'^kb/(?P<slug>[A-Za-z0-9_-]+)/$',
            kb.category,
            name='kb_category'),
    ]

urlpatterns += [
    url(r'^help/context/$',
        TemplateView.as_view(template_name='helpdesk/help_context.html'),
        name='help_context'),
]

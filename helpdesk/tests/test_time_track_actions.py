from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client

from helpdesk.models import Queue, Ticket, TicketTimeTrack

try:  # python 3
    from urllib.parse import urlparse
except ImportError:  # python 2
    from urlparse import urlparse


class TicketTimeTrackActionsTestCase(TestCase):
    fixtures = ['emailtemplate.json']

    def setUp(self):
        self.queue = Queue.objects.create(title='Q1', slug='q1')

        self.ticket = Ticket.objects.create(title='Test Ticket', submitter_email='test@domain.com', queue=self.queue)
        self.client = Client()

    def loginUser(self, is_staff=True):
        User = get_user_model()
        self.user = User.objects.create(
            username='User_1',
            is_staff=is_staff,
        )
        pwd = 'pass'
        self.user.set_password(pwd)
        self.user.save()
        self.client.login(username=self.user.username, password=pwd)

    def test_delete_ticket_time_track(self):
        """Tests whether staff can delete ticket time track"""

        self.loginUser()

        time_track = TicketTimeTrack.objects.create(ticket=self.ticket, time=timedelta(minutes=12),
                                                    tracked_by=self.user)
        time_track_id = time_track.id
        url = reverse('helpdesk:ticket_time_track_delete', kwargs={'pk': time_track_id})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Are you sure you want to delete Time Track ')

        response = self.client.post(url, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))

        # test ticket deleted
        with self.assertRaises(TicketTimeTrack.DoesNotExist):
            TicketTimeTrack.objects.get(pk=time_track_id)

    def test_delete_ticket_time_track_no_permission(self):
        """Tests whether staff can delete ticket time track"""

        self.loginUser()
        # create second user
        User = get_user_model()
        user2 = User.objects.create(
            username='User_2',
            is_staff=True,
        )
        time_track = TicketTimeTrack.objects.create(ticket=self.ticket, time=timedelta(minutes=12),
                                                    tracked_by=user2)
        time_track_id = time_track.id
        url = reverse('helpdesk:ticket_time_track_delete', kwargs={'pk': time_track_id})
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_update_ticket_time_track(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()

        initial_data = dict(ticket=self.ticket, time=timedelta(minutes=12), tracked_by=self.user)
        time_track = TicketTimeTrack.objects.create(**initial_data)
        time_track_id = time_track.id
        url = reverse('helpdesk:ticket_time_track_edit', kwargs={'pk': time_track_id})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Edit Ticket Time Track')

        post_data = {
            'time': '0:15:0',
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))
        time_track.refresh_from_db()
        self.assertEqual(time_track.time, timedelta(minutes=15))
        self.assertEqual(time_track.tracked_at, post_data['tracked_at'])

    def test_update_ticket_time_track_no_permission(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()

        # create second user
        User = get_user_model()
        user2 = User.objects.create(
            username='User_2',
            is_staff=True,
        )

        initial_data = dict(ticket=self.ticket, time=timedelta(minutes=12), tracked_by=user2)
        time_track = TicketTimeTrack.objects.create(**initial_data)
        time_track_id = time_track.id
        url = reverse('helpdesk:ticket_time_track_edit', kwargs={'pk': time_track_id})
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 403)

        post_data = {
            'time': '0:15:0',
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_add_ticket_time_track(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()
        url = reverse('helpdesk:ticket_time_track_add', kwargs={'ticket_id': self.ticket.pk})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Add Ticket Time Track')

        post_data = {
            'time': '0:15:0',
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))
        time_track = TicketTimeTrack.objects.get(tracked_at=post_data['tracked_at'])
        self.assertEqual(time_track.time, timedelta(minutes=15))

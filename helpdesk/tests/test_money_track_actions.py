from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client

from helpdesk.models import Queue, Ticket, TicketMoneyTrack

try:  # python 3
    from urllib.parse import urlparse
except ImportError:  # python 2
    from urlparse import urlparse


class TicketMoneyTrackActionsTestCase(TestCase):
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

    def test_delete_ticket_money_track(self):
        """Tests whether staff can delete ticket money track"""

        self.loginUser()

        money_track = TicketMoneyTrack.objects.create(ticket=self.ticket, money=12,
                                                    tracked_by=self.user)
        money_track_id = money_track.id
        url = reverse('helpdesk:ticket_money_track_delete', kwargs={'pk': money_track_id})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Are you sure you want to delete Money Track ')

        response = self.client.post(url, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))

        # test ticket deleted
        with self.assertRaises(TicketMoneyTrack.DoesNotExist):
            TicketMoneyTrack.objects.get(pk=money_track_id)

    def test_delete_ticket_money_track_no_permission(self):
        """Tests whether staff can delete ticket money track"""

        self.loginUser()
        # create second user
        User = get_user_model()
        user2 = User.objects.create(
            username='User_2',
            is_staff=True,
        )
        money_track = TicketMoneyTrack.objects.create(ticket=self.ticket, money=12,
                                                    tracked_by=user2)
        money_track_id = money_track.id
        url = reverse('helpdesk:ticket_money_track_delete', kwargs={'pk': money_track_id})
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_update_ticket_money_track(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()

        initial_data = dict(ticket=self.ticket, money=12, tracked_by=self.user)
        money_track = TicketMoneyTrack.objects.create(**initial_data)
        money_track_id = money_track.id
        url = reverse('helpdesk:ticket_money_track_edit', kwargs={'pk': money_track_id})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Edit Ticket Money Track')

        post_data = {
            'money': 15,
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))
        money_track.refresh_from_db()
        self.assertEqual(money_track.money, 15)
        self.assertEqual(money_track.tracked_at, post_data['tracked_at'])

    def test_update_ticket_money_track_no_permission(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()

        # create second user
        User = get_user_model()
        user2 = User.objects.create(
            username='User_2',
            is_staff=True,
        )

        initial_data = dict(ticket=self.ticket, money=12, tracked_by=user2)
        money_track = TicketMoneyTrack.objects.create(**initial_data)
        money_track_id = money_track.id
        url = reverse('helpdesk:ticket_money_track_edit', kwargs={'pk': money_track_id})
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 403)

        post_data = {
            'money': 15,
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_add_ticket_money_track(self):
        """Tests whether staff can update ticket details"""

        self.loginUser()
        url = reverse('helpdesk:ticket_money_track_add', kwargs={'ticket_id': self.ticket.pk})
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Add Ticket Money Track')

        post_data = {
            'money': 15,
            'tracked_at': timezone.now()
        }
        response = self.client.post(url, post_data, follow=True)
        first_redirect = response.redirect_chain[0]
        first_redirect_url = first_redirect[0]
        urlparts = urlparse(first_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk:view', kwargs={'ticket_id': self.ticket.pk}))
        money_track = TicketMoneyTrack.objects.get(tracked_at=post_data['tracked_at'])
        self.assertEqual(money_track.money, 15)

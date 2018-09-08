# -*- coding: utf-8 -*-
from django.core.urlresolvers import reverse
from django.test import TestCase
from helpdesk.models import Queue
from helpdesk.tests.helpers import get_staff_user


class TestSavingSharedQuery(TestCase):
    def setUp(self):
        q = Queue(title='Q1', slug='q1')
        q.save()
        self.q = q

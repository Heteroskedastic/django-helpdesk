# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2017-08-19 11:36
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone

# noinspection PyPep8Naming,PyUnusedLocal
def forwards_func(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Ticket = apps.get_model("helpdesk", "Ticket")
    FollowUp = apps.get_model("helpdesk", "FollowUp")
    for ticket in Ticket.objects.using(db_alias).all():
        follow_up = FollowUp.objects.filter(ticket=ticket).exclude(new_status=None).last()
        ticket.modified_status = follow_up and follow_up.date
        if not ticket.modified_status:
            print('Not Found follow up for ticket #{}! set default!'.format(ticket.id))
            ticket.modified_status = ticket.created or timezone.now()

        ticket.save(update_fields=['modified_status'])


# noinspection PyUnusedLocal
def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0022_ticketnotification_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='modified_status',
            field=models.DateTimeField(auto_now_add=True, default=timezone.now, help_text='Date this ticket status changed.', verbose_name='Modified Status'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='ticket',
            name='priority',
            field=models.IntegerField(blank=3, choices=[(1, 'Critical'), (2, 'High'), (3, 'Normal'), (4, 'Low'), (5, 'Very Low')], default=3, help_text='1 = Highest Priority, 5 = Low Priority', verbose_name='Priority'),
        ),
        migrations.RunPython(forwards_func, reverse_func),
    ]

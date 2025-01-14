# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-08-16 19:12
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ExclusivenessConfig',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=True, help_text="Caution! If you'll disable exclusiveness and you are not superadmin you won't be able to enable it again!", verbose_name='enabled')),
                ('start_date', models.DateTimeField(default=django.utils.timezone.now, verbose_name='start date')),
                ('end_date', models.DateTimeField(blank=True, null=True, verbose_name='end date')),
            ],
            options={
                'verbose_name': 'exclusiveness config',
                'verbose_name_plural': 'exclusiveness configs',
            },
        ),
    ]

# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-08-21 15:41
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('problems', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RemoteProblemURL',
            fields=[
                ('problem', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='problems.Problem')),
                ('url', models.CharField(max_length=255)),
            ],
        ),
    ]

# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2016-07-24 14:28
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapi', '0005_workbooktype_mandatory_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='workbooktype',
            name='mandatory_fields',
            field=models.TextField(help_text=b"Comma separated visitor table's column name (eg: name,mobile_no)", max_length=1250, null=True),
        ),
    ]
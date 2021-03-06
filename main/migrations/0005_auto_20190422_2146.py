# Generated by Django 2.0.13 on 2019-04-23 04:46

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_memberphoto'),
    ]

    operations = [
        migrations.AddField(
            model_name='inboundsms',
            name='extra_info',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='inboundsms',
            name='member',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='inboundsms',
            name='no',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='inboundsms',
            name='outbound',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.OutboundSms'),
        ),
        migrations.AddField(
            model_name='inboundsms',
            name='yes',
            field=models.BooleanField(default=False),
        ),
    ]

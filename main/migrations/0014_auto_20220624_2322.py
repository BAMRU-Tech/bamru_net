# Generated by Django 3.2.13 on 2022-06-25 06:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0013_event_cal_private'),
    ]

    operations = [
        migrations.AlterField(
            model_name='distribution',
            name='rsvp_answer',
            field=models.BooleanField(null=True),
        ),
        migrations.AlterField(
            model_name='doavailable',
            name='available',
            field=models.BooleanField(default=None, null=True),
        ),
        migrations.AlterField(
            model_name='role',
            name='role',
            field=models.CharField(blank=True, choices=[('UL', 'Unit Leader'), ('Bd', 'Board Member'), ('XO', 'Executive Officer'), ('OO', 'Operations Officer'), ('SEC', 'Secretary'), ('TO', 'Training Officer'), ('RO', 'Recruiting Officer'), ('TRS', 'Treasurer'), ('OL', 'Operation Leader'), ('WEB', 'Web Master'), ('DOS', 'DO Scheduler')], max_length=255),
        ),
    ]

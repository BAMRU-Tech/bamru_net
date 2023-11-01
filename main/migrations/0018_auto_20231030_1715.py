# Generated by Django 3.2.16 on 2023-10-31 00:15

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0017_auto_20231029_2157'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalmember',
            name='status',
        ),
        migrations.RemoveField(
            model_name='member',
            name='status',
        ),
        migrations.RenameField(
            model_name='historicalmember',
            old_name='status_fk',
            new_name='status',
        ),
        migrations.RenameField(
            model_name='member',
            old_name='status_fk',
            new_name='status',
        ),
    ]

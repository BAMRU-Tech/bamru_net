# Generated by Django 2.0.8 on 2019-01-16 02:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0002_auto_20181231_1341'),
    ]

    operations = [
        migrations.AlterField(
            model_name='email',
            name='type',
            field=models.CharField(choices=[('Home', 'Home'), ('Personal', 'Personal'), ('Work', 'Work'), ('Other', 'Other')], default='Personal', max_length=255),
        ),
        migrations.AlterField(
            model_name='message',
            name='linked_rsvp',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.Message'),
        ),
        migrations.AlterField(
            model_name='message',
            name='period',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.Period'),
        ),
        migrations.AlterField(
            model_name='message',
            name='rsvp_template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.RsvpTemplate'),
        ),
        migrations.AlterField(
            model_name='outboundemail',
            name='email',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.Email'),
        ),
        migrations.AlterField(
            model_name='outboundsms',
            name='phone',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.Phone'),
        ),
        migrations.AlterField(
            model_name='phone',
            name='type',
            field=models.CharField(choices=[('Home', 'Home'), ('Mobile', 'Mobile'), ('Work', 'Work'), ('Pager', 'Pager'), ('Other', 'Other')], default='Mobile', max_length=255),
        ),
    ]
# Generated by Django 2.2.13 on 2020-08-08 23:18

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0008_documenttemplate_dolog'),
    ]

    operations = [
        migrations.CreateModel(
            name='AhcLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('fileId', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='LogisticsSpreadsheet',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('fileId', models.CharField(blank=True, max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.RemoveField(
            model_name='dolog',
            name='type',
        ),
        migrations.AddConstraint(
            model_name='dolog',
            constraint=models.UniqueConstraint(fields=('year', 'quarter', 'week'), name='unique_do_log'),
        ),
        migrations.AddField(
            model_name='logisticsspreadsheet',
            name='event',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='logistics_spreadsheet', to='main.Event'),
        ),
        migrations.AddField(
            model_name='ahclog',
            name='event',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='ahc_log', to='main.Event'),
        ),
    ]

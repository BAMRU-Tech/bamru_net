# Generated by Django 2.2.13 on 2020-08-20 03:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0009_docs_20200808'),
    ]

    operations = [
        migrations.CreateModel(
            name='Aar',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('fileId', models.CharField(blank=True, max_length=255)),
                ('event', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='aar', to='main.Event')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]

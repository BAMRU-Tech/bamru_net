# Generated by Django 2.0.8 on 2018-12-21 01:50

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import main.models.file
import main.models.member
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0009_alter_user_last_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Member',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('first_name', models.CharField(max_length=255)),
                ('last_name', models.CharField(max_length=255)),
                ('username', models.CharField(max_length=255, unique=True)),
                ('status', models.CharField(blank=True, choices=[('TM', 'Technical Member'), ('FM', 'Field Member'), ('T', 'Trainee'), ('R', 'Reserve'), ('S', 'Support'), ('A', 'Associate'), ('G', 'Guest'), ('MA', 'Member Alum'), ('GA', 'Guest Alum'), ('MN', 'Member No-contact'), ('GN', 'Guest No-contact')], max_length=255)),
                ('dl', models.CharField(blank=True, max_length=255, null=True)),
                ('ham', models.CharField(blank=True, max_length=255, null=True)),
                ('v9', models.CharField(blank=True, max_length=255, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('is_staff', models.BooleanField(default=False)),
                ('is_current_do', models.BooleanField(default=False)),
                ('sign_in_count', models.IntegerField(default=0)),
                ('last_sign_in_at', models.DateTimeField(blank=True, null=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.Group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.Permission', verbose_name='user permissions')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Address',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('type', models.CharField(choices=[('home', 'home TODO'), ('Home', 'Home'), ('Work', 'Work'), ('Other', 'Other')], max_length=255)),
                ('address1', models.CharField(max_length=255)),
                ('address2', models.CharField(blank=True, max_length=255)),
                ('city', models.CharField(max_length=255)),
                ('state', models.CharField(max_length=255)),
                ('zip', models.CharField(max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Cert',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('type', models.CharField(choices=[('medical', 'Medical'), ('cpr', 'CPR'), ('ham', 'Ham'), ('tracking', 'Tracking'), ('avalanche', 'Avalanche'), ('rigging', 'Rigging'), ('ics', 'ICS'), ('overhead', 'Overhead'), ('driver', 'SO Driver'), ('background', 'SO Background')], max_length=255)),
                ('expires_on', models.DateField(blank=True, null=True)),
                ('description', models.CharField(max_length=255)),
                ('comment', models.CharField(blank=True, max_length=255, null=True)),
                ('link', models.CharField(blank=True, max_length=255, null=True)),
                ('cert_file', models.FileField(blank=True, max_length=255, null=True, upload_to=main.models.member.cert_upload_path_handler)),
                ('cert_name', models.CharField(blank=True, max_length=255, null=True)),
                ('cert_content_type', models.CharField(blank=True, max_length=255, null=True)),
                ('cert_size', models.TextField(blank=True, null=True)),
                ('ninety_day_notice_sent_at', models.DateTimeField(blank=True, null=True)),
                ('thirty_day_notice_sent_at', models.DateTimeField(blank=True, null=True)),
                ('expired_notice_sent_at', models.DateTimeField(blank=True, null=True)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Configuration',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('key', models.CharField(max_length=255, unique=True)),
                ('value', models.CharField(max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DataFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('file', models.FileField(max_length=255, null=True, upload_to=main.models.file.file_upload_path_handler)),
                ('name', models.CharField(max_length=255)),
                ('extension', models.CharField(max_length=255)),
                ('content_type', models.CharField(max_length=255)),
                ('size', models.IntegerField()),
                ('caption', models.CharField(blank=True, max_length=255, null=True)),
                ('download_count', models.IntegerField(default=0)),
                ('published', models.BooleanField(default=False)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Distribution',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('send_email', models.BooleanField(default=False)),
                ('send_sms', models.BooleanField(default=False)),
                ('read', models.BooleanField(default=False)),
                ('bounced', models.BooleanField(default=False)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('response_seconds', models.IntegerField(blank=True, null=True)),
                ('rsvp', models.BooleanField(default=False)),
                ('rsvp_answer', models.NullBooleanField()),
                ('unauth_rsvp_token', models.CharField(default=uuid.uuid4, editable=False, max_length=255, null=True, unique=True)),
                ('unauth_rsvp_expires_at', models.DateTimeField(blank=True, null=True)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DoAvailable',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year', models.IntegerField()),
                ('quarter', models.IntegerField()),
                ('week', models.IntegerField()),
                ('available', models.BooleanField(default=False)),
                ('assigned', models.BooleanField(default=False)),
                ('comment', models.CharField(blank=True, max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Email',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('type', models.CharField(choices=[('Home', 'Home'), ('Personal', 'Personal'), ('Work', 'Work'), ('Other', 'Other')], max_length=255)),
                ('pagable', models.BooleanField(default=True)),
                ('address', models.CharField(max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='EmergencyContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('name', models.CharField(max_length=255)),
                ('number', models.CharField(max_length=255)),
                ('type', models.CharField(choices=[('Home', 'Home'), ('Mobile', 'Mobile'), ('Work', 'Work'), ('Other', 'Other')], max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('type', models.CharField(choices=[('meeting', 'Meeting'), ('operation', 'Operation'), ('training', 'Training'), ('community', 'Community')], max_length=255)),
                ('title', models.CharField(max_length=255)),
                ('leaders', models.CharField(blank=True, max_length=255, null=True)),
                ('description', models.TextField(blank=True, null=True)),
                ('location', models.CharField(max_length=255)),
                ('lat', models.CharField(blank=True, max_length=255, null=True)),
                ('lon', models.CharField(blank=True, max_length=255, null=True)),
                ('start_at', models.DateTimeField()),
                ('finish_at', models.DateTimeField()),
                ('all_day', models.BooleanField(default=False, help_text='All Day events do not have a start or end time.')),
                ('published', models.BooleanField(default=False, help_text='Published events are viewable by the public.')),
                ('gcal_id', models.TextField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='InboundSms',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sid', models.CharField(blank=True, max_length=255, null=True)),
                ('from_number', models.CharField(blank=True, max_length=255, null=True)),
                ('to_number', models.CharField(blank=True, max_length=255, null=True)),
                ('body', models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Message',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('text', models.TextField()),
                ('format', models.CharField(choices=[('page', 'Page'), ('password_reset', 'Password reset'), ('cert_notice', 'Cert notice'), ('do_shift_starting', 'DO Shift Starting'), ('do_shift_pending', 'DO Shift Pending')], max_length=255)),
                ('ancestry', models.CharField(blank=True, max_length=255, null=True)),
                ('period_format', models.CharField(blank=True, choices=[('invite', 'invite'), ('info', 'info'), ('broadcast', 'broadcast'), ('leave', 'leave'), ('return', 'return'), ('test', 'test')], max_length=255, null=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('linked_rsvp', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.Message')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='OtherInfo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('label', models.CharField(max_length=255)),
                ('value', models.CharField(max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='OutboundEmail',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('destination', models.CharField(blank=True, max_length=255)),
                ('sid', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(blank=True, max_length=255)),
                ('error_message', models.TextField(blank=True)),
                ('sending_started', models.BooleanField(default=False)),
                ('delivered', models.BooleanField(default=False)),
                ('opened', models.BooleanField(default=False)),
                ('distribution', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Distribution')),
                ('email', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Email')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='OutboundSms',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('destination', models.CharField(blank=True, max_length=255)),
                ('sid', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(blank=True, max_length=255)),
                ('error_message', models.TextField(blank=True)),
                ('sending_started', models.BooleanField(default=False)),
                ('delivered', models.BooleanField(default=False)),
                ('error_code', models.IntegerField(blank=True, null=True)),
                ('source', models.CharField(blank=True, max_length=255)),
                ('distribution', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Distribution')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Participant',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('ahc', models.BooleanField(default=False)),
                ('ol', models.BooleanField(default=False)),
                ('comment', models.CharField(blank=True, max_length=255, null=True)),
                ('en_route_at', models.DateTimeField(blank=True, null=True)),
                ('return_home_at', models.DateTimeField(blank=True, null=True)),
                ('signed_in_at', models.DateTimeField(blank=True, null=True)),
                ('signed_out_at', models.DateTimeField(blank=True, null=True)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Period',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('start_at', models.DateTimeField(blank=True, null=True)),
                ('finish_at', models.DateTimeField(blank=True, null=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Event')),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Phone',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('type', models.CharField(choices=[('Home', 'Home'), ('Mobile', 'Mobile'), ('Work', 'Work'), ('Pager', 'Pager'), ('Other', 'Other')], max_length=255)),
                ('number', models.CharField(max_length=255)),
                ('pagable', models.BooleanField(default=True)),
                ('sms_email', models.CharField(blank=True, max_length=255, null=True)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Role',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('role', models.CharField(blank=True, choices=[('UL', 'Unit Leader'), ('Bd', 'Board Member'), ('XO', 'Executive Officer'), ('OO', 'Operations Officer'), ('SEC', 'Secretary'), ('TO', 'Training Officer'), ('RO', 'Recruiting Officer'), ('TRS', 'Treasurer'), ('OL', 'Operators Leader'), ('WEB', 'Web Master'), ('REG', 'Registar'), ('TM', 'Active Technical Member'), ('FM', 'Active Field Member'), ('T', 'Active Trainee')], max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RsvpTemplate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('position', models.IntegerField(default=1, null=True)),
                ('name', models.CharField(blank=True, max_length=255, null=True)),
                ('prompt', models.CharField(blank=True, max_length=255, null=True)),
                ('yes_prompt', models.CharField(blank=True, max_length=255, null=True)),
                ('no_prompt', models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                'abstract': False,
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='Unavailable',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('start_on', models.DateField(blank=True, null=True)),
                ('end_on', models.DateField(blank=True, null=True)),
                ('comment', models.CharField(blank=True, max_length=255)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='participant',
            name='period',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Period'),
        ),
        migrations.AddField(
            model_name='outboundsms',
            name='phone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Phone'),
        ),
        migrations.AddField(
            model_name='message',
            name='period',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.Period'),
        ),
        migrations.AddField(
            model_name='message',
            name='rsvp_template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.RsvpTemplate'),
        ),
        migrations.AddField(
            model_name='distribution',
            name='message',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.Message'),
        ),
    ]
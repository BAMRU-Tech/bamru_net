# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models
from django_twilio.client import twilio_client

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Member(BaseModel):
    TYPES = (
        ('TM', 'Technical Member'),
        ('FM', 'Field Member'),
        ('T', 'Trainee'),
        ('R', 'Reserve'),
        ('S', 'Support'),
        ('A', 'Associate'),
        ('G', 'Guest'),
        ('MA', 'Member Alum'),
        ('GA', 'Guest Alum'),
        ('MN', 'Member No-contact'),
        ('GN', 'Guest No-contact'),
        )

    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    user_name = models.CharField(max_length=255, blank=True, null=True)
    typ = models.CharField(choices=TYPES, max_length=255, blank=True, null=True)
    dl = models.CharField(max_length=255, blank=True, null=True)
    ham = models.CharField(max_length=255, blank=True, null=True)
    v9 = models.CharField(max_length=255, blank=True, null=True)
    admin = models.NullBooleanField()
    developer = models.NullBooleanField()
    current_do = models.NullBooleanField()
    sign_in_count = models.IntegerField(blank=True, null=True)
    ip_address = models.CharField(max_length=255, blank=True, null=True)
    last_sign_in_at = models.DateTimeField(blank=True, null=True)

    # remove fields below here
    title = models.CharField(max_length=255, blank=True, null=True)
    role_score = models.IntegerField(blank=True, null=True)
    typ_score = models.IntegerField(blank=True, null=True)
    password_digest = models.CharField(max_length=255, blank=True, null=True)  # This field type is a guess.
    remember_me_token = models.CharField(max_length=255, blank=True, null=True)  # This field type is a guess.
    forgot_password_token = models.CharField(max_length=255, unique=True, blank=True, null=True)  # This field type is a guess.
    forgot_password_expires_at = models.DateTimeField(blank=True, null=True)
    google_oauth_token = models.CharField(max_length=255, blank=True, null=True)  # This field type is a guess.
    remember_created_at = models.TimeField(blank=True, null=True)

    def __str__(self):
        return "{} {}".format(self.first_name, self.last_name)
    
    class Meta:
        db_table = 'members'


class Address(BaseModel):
    TYPES = (
        ('home', 'home FIXME'),
        ('Home', 'Home'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    typ = models.CharField(choices=TYPES, max_length=255)
    address1 = models.CharField(max_length=255, blank=True, null=True)
    address2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    zip = models.CharField(max_length=255, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return "{}, {}, {}, {} {}".format(self.address1, self.address2, self.city, self.state, self.zip)
    class Meta:
        db_table = 'addresses'

class Email(BaseModel):
    TYPES = (
        ('Home', 'Home'),
        ('Personal', 'Personal'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    typ = models.CharField(choices=TYPES, max_length=255)
    pagable = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    class Meta:
        db_table = 'emails'


class Phone(BaseModel):
    TYPES = (
        ('Home', 'Home'),
        ('Mobile', 'Mobile'),
        ('Work', 'Work'),
        ('Pager', 'Pager'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    typ = models.CharField(choices=TYPES, max_length=255)
    number = models.CharField(max_length=255, blank=True, null=True)
    pagable = models.CharField(max_length=255, blank=True, null=True)
    sms_email = models.CharField(max_length=255, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    class Meta:
        db_table = 'phones'

class EmergencyContact(BaseModel):
    TYPES = (
        ('Home', 'Home'),
        ('Mobile', 'Mobile'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True, null=True)
    number = models.CharField(max_length=255, blank=True, null=True)
    typ = models.CharField(choices=TYPES, max_length=255, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    class Meta:
        db_table = 'emergency_contacts'

# UL, XO, OO, SEC, TO, TRS, REG, WEB, Bd, OL,
class Role(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    typ = models.CharField(max_length=255, blank=True, null=True)  # TODO choices
    class Meta:
        db_table = 'roles'

class OtherInfo(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    label = models.CharField(max_length=255, blank=True, null=True)
    value = models.CharField(max_length=255, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    class Meta:
        db_table = 'other_infos'


################## Events ###########################################

class Event(BaseModel):
    typ = models.CharField(max_length=255, blank=True, null=True)  # TODO choice
    title = models.CharField(max_length=255, blank=True, null=True)
    leaders = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    lat = models.CharField(max_length=255, blank=True, null=True)
    lon = models.CharField(max_length=255, blank=True, null=True)
    start = models.DateTimeField(blank=True, null=True)
    finish = models.DateTimeField(blank=True, null=True)
    all_day = models.NullBooleanField()
    published = models.NullBooleanField()
    def __str__(self):
        return self.title
    class Meta:
        db_table = 'events'

class Period(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    position = models.IntegerField(blank=True, null=True)
    start = models.DateTimeField(blank=True, null=True)
    finish = models.DateTimeField(blank=True, null=True)
    rsvp_id = models.IntegerField(blank=True, null=True)  # TODO
    def __str__(self):
        return "{} OP{}".format(self.event.title, self.position)
    class Meta:
        db_table = 'periods'

class Participant(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    ahc = models.NullBooleanField()
    ol = models.NullBooleanField()
    period = models.ForeignKey(Period, on_delete=models.CASCADE)
    comment = models.CharField(max_length=255, blank=True, null=True)
    en_route_at = models.DateTimeField(blank=True, null=True)
    return_home_at = models.DateTimeField(blank=True, null=True)
    signed_in_at = models.DateTimeField(blank=True, null=True)
    signed_out_at = models.DateTimeField(blank=True, null=True)
    class Meta:
        db_table = 'participants'

#####################################################################

class Message(BaseModel):
    author = models.ForeignKey(Member, on_delete=models.CASCADE)
    ip_address = models.CharField(max_length=255, blank=True, null=True)
    text = models.TextField(blank=True, null=True)
    format = models.CharField(max_length=255, blank=True, null=True)
    linked_rsvp_id = models.IntegerField(blank=True, null=True)  # TODO: foreign key
    ancestry = models.CharField(max_length=255, blank=True, null=True)
    period_id = models.IntegerField(blank=True, null=True)  # TODO: foreign key
    period_format = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'messages'


class Distribution(BaseModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    email = models.NullBooleanField()
    phone = models.NullBooleanField()
    read = models.NullBooleanField()
    bounced = models.NullBooleanField()
    read_at = models.DateTimeField(blank=True, null=True)
    response_seconds = models.IntegerField(blank=True, null=True)
    rsvp = models.NullBooleanField()
    rsvp_answer = models.CharField(max_length=255, blank=True, null=True)  # TODO: Yes/No -> bool
    unauth_rsvp_token = models.CharField(max_length=255, unique=True, blank=True, null=True)
    unauth_rsvp_expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'distributions'

class OutboundSms(BaseModel):
    distribution = models.ForeignKey(Distribution, on_delete=models.CASCADE)
    phone = models.ForeignKey(Phone, on_delete=models.CASCADE)
    member_number = models.CharField(max_length=255, blank=False, null=False)

    def send(self):
        self.member_number = self.phone.number
        twilio_client.messages.create(
            body=self.distribution.message.text,
            to=self.member_number,
            from_="415-599-2671",
            )

#####################################################################
# Models below this line have not been looked at
#####################################################################


class AvailDos(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    quarter = models.IntegerField(blank=True, null=True)
    week = models.IntegerField(blank=True, null=True)
    typ = models.TextField(blank=True, null=True)  # This field type is a guess.
    comment = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'avail_dos'


class AvailOps(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    start_on = models.DateField(blank=True, null=True)
    end_on = models.DateField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'avail_ops'


class Certs(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    typ = models.TextField(blank=True, null=True)  # This field type is a guess.
    expiration = models.DateField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)  # This field type is a guess.
    comment = models.TextField(blank=True, null=True)  # This field type is a guess.
    link = models.TextField(blank=True, null=True)  # This field type is a guess.
    position = models.IntegerField(blank=True, null=True)
    cert_file = models.TextField(blank=True, null=True)  # This field type is a guess.
    cert_file_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    cert_content_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    cert_file_size = models.TextField(blank=True, null=True)  # This field type is a guess.
    cert_updated_at = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    ninety_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    thirty_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    expired_notice_sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'certs'


class DataFiles(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    download_count = models.IntegerField(blank=True, null=True)
    data_file_extension = models.TextField(blank=True, null=True)  # This field type is a guess.
    data_file_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    data_file_size = models.TextField(blank=True, null=True)  # This field type is a guess.
    data_content_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    data_updated_at = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    killme1 = models.IntegerField(blank=True, null=True)
    killme2 = models.IntegerField(blank=True, null=True)
    caption = models.TextField(blank=True, null=True)  # This field type is a guess.
    published = models.NullBooleanField()

    class Meta:
        managed = False
        db_table = 'data_files'


class DataLinks(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    site_url = models.TextField(blank=True, null=True)  # This field type is a guess.
    caption = models.TextField(blank=True, null=True)  # This field type is a guess.
    published = models.NullBooleanField()
    link_backup_file_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    link_backup_content_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    link_backup_file_size = models.IntegerField(blank=True, null=True)
    link_backup_updated_at = models.IntegerField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'data_links'


class DataPhotos(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    caption = models.TextField(blank=True, null=True)  # This field type is a guess.
    image_file_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    image_content_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    image_file_size = models.IntegerField(blank=True, null=True)
    image_updated_at = models.IntegerField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    published = models.NullBooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'data_photos'


class DoAssignments(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    org_id = models.IntegerField(blank=True, null=True)
    year = models.IntegerField(blank=True, null=True)
    quarter = models.IntegerField(blank=True, null=True)
    week = models.IntegerField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    primary_id = models.IntegerField(blank=True, null=True)
    backup_id = models.IntegerField(blank=True, null=True)
    start = models.DateTimeField(blank=True, null=True)
    finish = models.DateTimeField(blank=True, null=True)
    reminder_notice_sent_at = models.DateTimeField(blank=True, null=True)
    alert_notice_sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'do_assignments'


class EventFiles(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_file_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'event_files'


class EventLinks(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_link_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'event_links'


class EventPhotos(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_photo_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'event_photos'


class EventReports(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    typ = models.TextField(blank=True, null=True)  # This field type is a guess.
    member_id = models.IntegerField(blank=True, null=True)
    event_id = models.IntegerField(blank=True, null=True)
    period_id = models.IntegerField(blank=True, null=True)
    title = models.TextField(blank=True, null=True)  # This field type is a guess.
    data = models.TextField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    published = models.NullBooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'event_reports'




class Photos(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    image_file_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    image_content_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    image_file_size = models.IntegerField(blank=True, null=True)
    image_updated_at = models.IntegerField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'photos'



class RsvpTemplates(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    position = models.IntegerField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)  # This field type is a guess.
    prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    yes_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    no_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'rsvp_templates'


class Rsvps(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    message_id = models.IntegerField(blank=True, null=True)
    prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    yes_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    no_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'rsvps'


################ Old messaging ###########################


class InboundMails(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    outbound_mail_id = models.IntegerField(blank=True, null=True)
    from_field = models.TextField(db_column='from', blank=True, null=True)  # Field renamed because it was a Python reserved word. This field type is a guess.
    to = models.TextField(blank=True, null=True)  # This field type is a guess.
    uid = models.TextField(blank=True, null=True)  # This field type is a guess.
    subject = models.TextField(blank=True, null=True)  # This field type is a guess.
    label = models.TextField(blank=True, null=True)  # This field type is a guess.
    body = models.TextField(blank=True, null=True)
    rsvp_answer = models.TextField(blank=True, null=True)  # This field type is a guess.
    send_time = models.DateTimeField(blank=True, null=True)
    bounced = models.NullBooleanField()
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    ignore_bounce = models.NullBooleanField()

    class Meta:
        managed = False
        db_table = 'inbound_mails'


class Journals(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    distribution_id = models.IntegerField(blank=True, null=True)
    action = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'journals'

class OutboundMails(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    distribution_id = models.IntegerField(blank=True, null=True)
    email_id = models.IntegerField(blank=True, null=True)
    phone_id = models.IntegerField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)  # This field type is a guess.
    label = models.TextField(blank=True, null=True)  # This field type is a guess.
    read = models.NullBooleanField()
    bounced = models.NullBooleanField()
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    sms_member_number = models.TextField(blank=True, null=True)  # This field type is a guess.
    sms_service_number = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'outbound_mails'


#################### remove ################################

class AlertSubscriptions(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_typ = models.TextField(blank=True, null=True)  # This field type is a guess.
    role_typ = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'alert_subscriptions'


class ArInternalMetadata(models.Model):
    key = models.TextField(primary_key=True)  # This field type is a guess.
    value = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ar_internal_metadata'

class BrowserProfiles(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    ip = models.TextField(blank=True, null=True)  # This field type is a guess.
    browser_type = models.TextField(blank=True, null=True)  # This field type is a guess.
    browser_version = models.TextField(blank=True, null=True)  # This field type is a guess.
    user_agent = models.TextField(blank=True, null=True)
    ostype = models.TextField(blank=True, null=True)  # This field type is a guess.
    javascript = models.NullBooleanField()
    cookies = models.NullBooleanField()
    screen_height = models.IntegerField(blank=True, null=True)
    screen_width = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'browser_profiles'

class Chats(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    client = models.TextField(blank=True, null=True)  # This field type is a guess.
    lat = models.TextField(blank=True, null=True)  # This field type is a guess.
    lon = models.TextField(blank=True, null=True)  # This field type is a guess.
    ip_address = models.TextField(blank=True, null=True)  # This field type is a guess.
    text = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'chats'


# was only 1 item: bamru
class Orgs(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    name = models.TextField(blank=True, null=True)  # This field type is a guess.
    class Meta:
        managed = False
        db_table = 'orgs'

class QueueClassicJobs(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    q_name = models.TextField(blank=True, null=True)  # This field type is a guess.
    method = models.TextField(blank=True, null=True)  # This field type is a guess.
    args = models.TextField(blank=True, null=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    class Meta:
        managed = False
        db_table = 'queue_classic_jobs'

class SchemaMigrations(models.Model):
    version = models.TextField(primary_key=True)  # This field type is a guess.
    class Meta:
        managed = False
        db_table = 'schema_migrations'

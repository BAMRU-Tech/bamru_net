
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


class AvailOps(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    start_on = models.DateField(blank=True, null=True)
    end_on = models.DateField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)


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


class EventFiles(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_file_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()


class EventLinks(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_link_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()


class EventPhotos(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    event_id = models.IntegerField(blank=True, null=True)
    data_photo_id = models.IntegerField(blank=True, null=True)
    keyval = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()


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



class RsvpTemplates(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    position = models.IntegerField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)  # This field type is a guess.
    prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    yes_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    no_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)


################ Old messaging ###########################

class Rsvps(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    message_id = models.IntegerField(blank=True, null=True)
    prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    yes_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    no_prompt = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

class Journals(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    distribution_id = models.IntegerField(blank=True, null=True)
    action = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

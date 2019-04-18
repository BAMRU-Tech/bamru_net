
#####################################################################
# Models below this line have not been looked at
#####################################################################

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

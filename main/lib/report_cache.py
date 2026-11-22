"""The activity reports' unit-wide work, kept between page loads: the unit
report's figures (unit_activity), the first day both reports count from
(counting.records_from), which the member page reads too, and what the unit
did (counting.unit_since), from which every member's report draws its unit
columns.

Each value is kept in the server process's cache (Django's default, one in
each worker), in one entry of its own, with what it was built from; it is
used again only while all of that still holds, and built again, in place,
when it does not:

- The data: for each table the value reads, its count of rows and its latest
  updated_at (its fingerprint), read on every load in one query for the page.
  So an edit, an addition or a deletion made through any worker is seen by
  every worker on its next load: an edit or an addition moves updated_at
  (every model the reports read sets it on save: BaseModel), a deletion moves
  the count. Each value reads only its own tables: a page rebuilds the first
  day but not the unit's days, an endorsement the unit's days but not the
  first day, and a reply or a busy period neither, only the unit report. A
  member's status history is not one of them: every login adds a row to it,
  and a change of status is a save of the member, which moves the members'
  fingerprint.
- The team's rules in force (report_settings) and the time zone.
- The time: the reports read it (an event counts once it has begun, an
  operation once it has finished, a DO week once its shift starts, nothing
  after today), so a value is used for the local date and the span of EXPIRY
  seconds it was built for, and time passing with no edit shows within it.

What is kept is plain data built in full, dates, numbers, strings and the
lists, sets and dicts of them, with no query or row in it to read later; the
cache stores a copy of it (pickled), and gives each caller its own."""
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from main.lib import counting
from main.lib import unit_activity as unit_report
from main.lib.report_settings import report_settings
from main.models import (Cert, CertSubType, CertType, DoAvailable, Distribution, Event, Member, Message, Participant,
                         Period, RsvpTemplate, Unavailable)

# How long a value built for one moment stands for the moments after it, in seconds: an operation that finishes,
# or an event that begins, with no edit, shows on the reports within this.
EXPIRY = 300

# The tables each value reads. The first day's (RECORDS) take in pages, as an operation with nobody listed and no
# page, since pages were first recorded, counts nowhere; what the unit did (UNIT_DAYS) takes in endorsements and
# their kinds, which date joining.
LOGGED = (Event, Period, Participant, Member)
RECORDS = LOGGED + (Message, DoAvailable)
UNIT_DAYS = LOGGED + (Cert, CertSubType, CertType)
UNIT_REPORT = RECORDS + (Cert, CertSubType, CertType, Distribution, RsvpTemplate, Unavailable)


def _read(tables):
    """Each of these models' fingerprint, its count of rows and latest
    updated_at, in one query: {label: (count, latest)}."""
    name = connection.ops.quote_name
    sql = ' UNION ALL '.join("SELECT '{}', COUNT(*), MAX({}) FROM {}".format(
        model._meta.label, name('updated_at'), name(model._meta.db_table)) for model in tables)
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return {label: (count, latest) for label, count, latest in cursor.fetchall()}


def _kept(name, prints, tables, now, build, *args):
    """The value `build()` gives, kept in the entry named `name` with what it
    was built from: the fingerprints of `tables` (of `prints`, as _read gives
    them), the team's rules, the time zone, the local date, the span of
    EXPIRY that `now` falls in, and `args`. Used again only while all of them
    are the same; built again, and the entry replaced, when they are not."""
    built_from = (sorted((model._meta.label, prints[model._meta.label]) for model in tables), report_settings(),
                  settings.TIME_ZONE, timezone.localtime(now).date(), int(now.timestamp() // EXPIRY), args)
    digest = hashlib.sha256(repr(built_from).encode()).hexdigest()
    key = 'activity-reports:' + name
    found = cache.get(key)
    if found is None or found[0] != digest:
        found = (digest, build())
        cache.set(key, found, EXPIRY)
    return found[1]


def unit_activity():
    """The unit report's figures, for its page: unit_activity, now."""
    now = timezone.now()
    return _kept('unit_activity', _read(UNIT_REPORT), UNIT_REPORT, now, lambda: unit_report.unit_activity(now))


def records_from(now):
    """The first day both reports count from, for the member page:
    counting.records_from(now)."""
    return _kept('records_from', _read(RECORDS), RECORDS, now, lambda: counting.records_from(now))


def member_report(now):
    """For a member's report: the first day both reports count from
    (counting.records_from), and a function that gives what the unit did from
    it on, up to `now` (counting.unit_since(since, now, since)), for
    counting.activity_rows to call only for a member with something to count;
    the tables both read are asked once. The function gives None with no
    records."""
    prints = _read({*RECORDS, *UNIT_DAYS})
    since = _kept('records_from', prints, RECORDS, now, lambda: counting.records_from(now))

    def unit_days():
        if since is None:
            return None
        return _kept('unit_since', prints, UNIT_DAYS, now, lambda: counting.unit_since(since, now, since), since)
    return since, unit_days

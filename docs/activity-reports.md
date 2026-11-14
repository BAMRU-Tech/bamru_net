# Activity reports

Three pages count what members do: a member's activity report, the "Last" table on the member page, and the
unit activity report. They share one set of rules, written once, in plain words, in the glossary at the foot
of each report. This page shows where each rule lives in the code, which setting changes it, and which tests
prove it.

## How a report is built

```mermaid
flowchart TD
    db["Database<br>events, periods, time logged, pages, DO weeks"]
    events["counting.py: reported_events<br>which events count"]
    member["counting.py, member side<br>activity_rows, listed_entries, member_latest"]
    unit["unit_counting.py<br>unit_rows: the unit's figures, year by year"]
    latest["member_latest.html<br>the member page's Last table"]
    activity["activity.py<br>member chart and table, shared glossary"]
    unitact["unit_activity.py<br>unit charts, their bands, unit glossary"]
    charts["charts.py<br>share_panels, with_menu: check a chart, size its marks"]
    draw["templates/charts, charts.css, charts.js<br>draw, switch, menus"]
    settings["report_settings.py<br>ACTIVITY_REPORTS, checked at start-up"]
    db --> events & member & unit
    settings -.-> events & member & unit & activity & unitact
    events --> member
    events --> unit
    member --> latest
    member --> activity
    unit --> unitact
    activity --> charts
    unitact --> charts
    charts --> draw
```

Solid arrows: what each step hands the next; the counting steps read the database through the events that
count. Dashed: the team's rules, which each step that applies one reads from `report_settings()`.

- `main/lib/counting.py` owns the rules both reports share: which events count, how logged time becomes days
  and hours, time logged twice, the end of today, whether an operation ran and why not, and where a member's
  report starts. It also counts a member's figures.
- `main/lib/unit_counting.py` counts the unit's figures; `main/lib/activity.py` and `main/lib/unit_activity.py`
  turn each report's figures into charts, tables and glossary rows.
- `main/lib/charts.py` and `templates/charts/` are the chart component: one small set of panels per chart,
  switches that work without script, and a figures box for each column.
- `main/models/event.py` reads an event's leaders text for the members it names, for the event page and for
  who led.
- `main/lib/report_settings.py` holds every rule a team may change, with BAMRU's values as the defaults.

## Rules, settings and tests

Each rule's key is in `ACTIVITY_REPORTS` (see the README); "—" means the rule is fixed. Tests are named as
module, class and method in `main/tests/`.

| Rule | Key | Tests |
|---|---|---|
| A calendar day with at least 2 hours logged for one event or operating period is a day attended. The time logged for each counts as at least one day whatever its hours, and 12 hours or less as one day, even across midnight. | `DAY_HOURS`, `SINGLE_DAY_HOURS` | `test_counting.DaysTestCase.test_days`<br>`test_report_settings.TeamRulesTestCase.test_day_hours_and_single_day_hours` |
| A member's hours count on the days they fell on, but a day too short to count gives them to the counted day beside it. The unit's active hours stay on the calendar days they fell on. | — | `test_counting.ActivityRowsTestCase.test_hours_go_to_the_days_they_fell_on`<br>`test_unit_activity.UnitActivityTestCase.test_the_units_hours_stay_on_the_days_they_fell_on_and_members_go_with_their_days` |
| Hours are time that passed; the 7 days an entry may run to are counted on the local clock, whatever the clocks did. | `MAX_ENTRY_DAYS` | `test_counting.DaysTestCase.test_daylight_saving`<br>`test_counting.DaysTestCase.test_seven_days_by_the_clock_in_the_weeks_the_clocks_change` |
| Time logged twice, on two periods or events at once, counts once, for the one that began first. | — | `test_counting.OverlappingTimeTestCase.test_time_logged_twice_counts_once`<br>`test_unit_activity.UnitActivityTestCase.test_time_logged_within_other_time_counts_once` |
| More than 7 days logged for one event or period is a mistake: one day, and no hours. | `MAX_ENTRY_DAYS` | `test_counting.ActivityRowsTestCase.test_an_entry_too_long_to_be_right`<br>`test_report_settings.TeamRulesTestCase.test_max_entry_days` |
| A day after today counts nothing yet, nor does an event that has not started, whatever its times. | — | `test_counting.ActivityRowsTestCase.test_time_entered_for_a_day_after_today_is_not_counted_yet`<br>`test_counting.EntryDaysTestCase.test_an_event_still_to_start_counts_nothing_whatever_its_times` |
| Guests are those whose status today is a guest's; their time counts only on their own report. Former members count. | — | `test_counting.ActivityRowsTestCase.test_alumni_count_towards_the_units_days_and_guests_do_not`<br>`test_unit_activity.UnitActivityTestCase.test_members_who_have_left_count_and_guests_do_not` |
| Events count whether published or not. | — | `test_counting.EventsAttendedTestCase.test_unpublished_events_count`<br>`test_unit_activity.UnitActivityTestCase.test_events_count_whether_published_or_not` |
| Test and demonstration events count nowhere, by their title. This pattern and `HEADS_UP_TITLE` run in the database, so at start-up a team's pattern is refused unless Postgres reads it as Python does: braces only as a bound, `{n}`, `{n,}` or `{n,m}` up to 255, no quantifier after a lookaround, and no `\b`. | `TEST_TITLE`, `HEADS_UP_TITLE` | `test_counting.ReportedEventsTestCase.test_test_and_demo_events_are_left_out`<br>`test_report_settings.TeamRulesTestCase.test_test_title`<br>`test_report_settings.ReportSettingsTestCase.test_a_wrong_value_is_refused_at_start_up_naming_its_key` |
| From the first page sent for an operation, other than a test's or a demonstration's, one with no page, nobody listed and no title calling it a heads-up was never used, and counts nowhere. | `HEADS_UP_TITLE` | `test_counting.ReportedEventsTestCase.test_operations_never_used_are_left_out`<br>`test_counting.PagingHistoryTestCase.test_with_no_page_recorded_no_operation_is_left_out_as_never_used`<br>`test_counting.PagingHistoryTestCase.test_pages_were_first_recorded_on_the_first_page_for_an_operation_a_report_counts`<br>`test_report_settings.TeamRulesTestCase.test_heads_up_title` |
| Only operations, trainings, meetings and community events count. | — | `test_member_report.ReportPagesTestCase.test_report_with_an_unknown_type_of_event` |
| On an operation, the OL in the field led it; elsewhere, those named in its leaders text or flagged OL did. | — | `test_counting.EntryLedTestCase.test_who_led`<br>`test_event_page.EventLeadersTestCase.test_members_named` |
| An operation ran once a member in the field, not a guest, has a day attended on it; it has finished once its start and its finish are both past. | — | `test_member_page.MemberLatestTestCase.test_an_operation_only_a_guest_logged_time_on_did_not_run`<br>`test_unit_activity.UnitActivityTestCase.test_operations_by_responders_and_called_off`<br>`test_member_page.MemberLatestTestCase.test_an_operation_saved_finishing_before_it_starts_has_not_finished_until_it_has_started` |
| An operation that did not run was called off if an availability page, with the callout reply template, went out for it, and only a heads-up if not. Before the first page with either reply template, or with none, its title decides: a heads-up if its title says so. A member listed on one called off stood down from it, unless it began before 2013, when whether it ran is not known. | `CALLOUT_TEMPLATE`, `HEADS_UP_TEMPLATE`, `HEADS_UP_TITLE`, `OPERATION_TIMES_FROM` | `test_counting.PagingHistoryTestCase.test_with_no_page_that_carried_a_reply_template_only_the_title_tells`<br>`test_report_settings.TeamRulesTestCase.test_callout_template`<br>`test_unit_activity.UnitActivityTestCase.test_a_teams_heads_up_template_tells_an_operation_only_warned_of`<br>`test_report_settings.TeamRulesTestCase.test_heads_up_title`<br>`test_member_page.MemberLatestTestCase.test_stood_down_once_the_operation_has_finished`<br>`test_member_page.MemberLatestTestCase.test_no_stood_down_line_for_an_operation_begun_before_operation_times_were_logged` |
| An operation had few responders, some or many. | `RESPONDERS_THIN`, `RESPONDERS_FULL` | `test_unit_activity.UnitActivityTestCase.test_a_team_sets_how_many_responders_are_few_and_how_many_many` |
| Callout pages are an operation's pages with the callout or the heads-up reply template. A member's reply to one, and to its repages, is timed once, from the first. | `REPLY_MINUTES`, `CALLOUT_TEMPLATE`, `HEADS_UP_TEMPLATE` | `test_unit_activity.UnitActivityTestCase.test_replies_to_callout_pages_by_how_soon`<br>`test_unit_activity.UnitActivityTestCase.test_a_team_sets_how_soon_a_reply_or_a_departure_is_quick`<br>`test_unit_activity.UnitActivityTestCase.test_a_team_names_the_reply_template_of_its_heads_up_pages`<br>`test_unit_activity.UnitActivityTestCase.test_pages_for_events_other_than_operations_are_not_callout_pages` |
| An immediate callout is an operation with a callout page that says "Immediate": at its start, after the operation's name and number as the page form begins a page, or after a repage, reply, forward or update prefix. It is timed from the first such page to the first departure logged after it by a member in the field, not a guest, up to today. | `IMMEDIATE_CALLOUT`, `IMMEDIATE_CALLOUT_SAID`, `DEPARTURE_MINUTES`, `CALLOUT_TEMPLATE`, `HEADS_UP_TEMPLATE` | `test_unit_activity.UnitActivityTestCase.test_which_pages_start_an_immediate_callout`<br>`test_unit_activity.UnitActivityTestCase.test_immediate_callouts_by_how_soon_the_first_responder_left`<br>`test_unit_activity.UnitActivityTestCase.test_a_guests_departure_and_one_after_today_are_left_out` |
| A one-day stretch in the field of more than 12 hours, door to door, is a long day; a longer stretch is counted by its days. | `LONG_DAY` | `test_unit_activity.UnitActivityTestCase.test_a_team_sets_how_many_hours_make_a_long_day`<br>`test_unit_activity.UnitActivityTestCase.test_twelve_hours_logged_in_three_parts_are_not_a_long_day` |
| A member joined on their third day at operations or at trainings not open to guests; with fewer than three such days, on their first event of any type. | `JOINED_AT`, `GUEST_FRIENDLY_TITLE` | `test_unit_activity.UnitActivityTestCase.test_a_team_sets_on_how_many_days_a_member_has_joined`<br>`test_unit_activity.UnitActivityTestCase.test_a_team_sets_which_trainings_are_open_to_guests` |
| A member is active in every calendar year from joining to the year of their last operation, training or community event, but for the years between leaving and coming back. They have left after 12 calendar months without one. Meetings do not keep a member active, though the day a member joins counts, whatever its event. | `LEFT_AFTER` | `test_unit_activity.UnitActivityTestCase.test_meetings_do_not_keep_a_member_active`<br>`test_unit_activity.UnitActivityTestCase.test_a_team_sets_the_months_after_which_a_member_has_left` |
| Responders are counted under the status they held on the day; some statuses have a band of their own. | `BANDED_STATUSES` | `test_unit_activity.UnitActivityTestCase.test_responders_by_the_status_they_held_on_the_day`<br>`test_unit_activity.UnitActivityTestCase.test_a_team_sets_which_statuses_have_a_band_of_their_own` |
| What is read from operation times is grey before the year they were first logged, on every chart that reads them. | `OPERATION_TIMES_FROM` | `test_unit_activity.UnitActivityTestCase.test_a_team_sets_the_year_from_which_operation_times_were_logged`<br>`test_unit_activity.UnitActivityTestCase.test_what_is_read_from_operation_times_is_grey_before_they_were_logged` |
| A run of 3 or more empty years cuts off a stray early record. The unit's first year is read from what the reports count by now: an event with a member's time, an operation that has finished, a DO week begun. Neither report counts anything dated before it, and an entry of an event dated earlier claims no time. | `STRAY_BEFORE` | `test_unit_activity.UnitActivityTestCase.test_a_team_sets_how_many_empty_years_mark_a_stray_record`<br>`test_counting.RecordsFromTestCase.test_a_time_typed_in_a_year_long_before_the_unit_s_counts_nowhere`<br>`test_counting.RecordsFromTestCase.test_only_what_a_report_counts_by_now_starts_the_records`<br>`test_counting.RecordsFromTestCase.test_an_entry_of_an_event_dated_before_the_records_claims_no_time_and_makes_no_unit_day` |
| An assigned DO week counts once its shift starts, in the month and year that hold most of its days; in its first three days, on today. | — | `test_counting.ActivityRowsTestCase.test_a_do_week_counts_in_the_year_that_holds_most_of_its_days`<br>`test_counting.RecordsFromTestCase.test_a_do_week_begun_in_december_counts_when_it_starts_the_records` |
| Hours are written to one decimal, half up, the same in every table, chart and list. | — | `test_charts.ChartsTestCase.test_hours_are_written_to_one_decimal`<br>`test_member_report.ReportPagesTestCase.test_an_entrys_row_and_the_totals_round_its_hours_alike` |

`test_docs.ActivityReportsPageTestCase` checks this table against the code: it fails if a test named here no
longer exists, or if a key of `ReportSettings` has no row. It cannot tell whether a test proves its row's rule:
that is for review.

## Out of scope

The older Activity Summary and Activity Detail reports are unchanged and do not use these rules. To run the
tests, see the README.

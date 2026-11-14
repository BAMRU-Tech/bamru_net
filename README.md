# BAMRU.net

## Running the tests

1. Install the requirements, with Python 3.13: `pip install -r requirements/test.txt`.
2. Copy `dot_env.sample` to `.env`. Its settings use SQLite, so no database server is needed.
3. Run `python manage.py test main`. The few tests that need API keys are skipped.

## Another team's rules

The activity reports' rules that differ from team to team, such as the hours that make a day attended or the
titles of test events, are set in `ACTIVITY_REPORTS` in `bamru_net/settings.py`: set only the keys to change.
Each key is listed, with its default, in `main/lib/report_settings.py`. How the reports are built, and the
rule, setting and tests behind each figure, are in [docs/activity-reports.md](docs/activity-reports.md).

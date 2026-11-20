"""docs/activity-reports.md stays true to the code: its rules table names tests that exist and every key a team
may set."""
import importlib
import os
import re
from dataclasses import fields

from django.conf import settings
from django.test import SimpleTestCase

from main.lib.report_settings import ReportSettings


class ActivityReportsPageTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        page = open(os.path.join(settings.BASE_DIR, 'docs', 'activity-reports.md')).read()
        # The rules table: its rows after the header and the line under it, as (rule, key, tests).
        rows = [line for line in page.splitlines() if line.startswith('| ')][1:]
        cls.rows = [[cell.strip() for cell in row.strip('|').split(' | ')] for row in rows]

    def test_the_table_has_a_rule_a_key_and_tests_in_every_row(self):
        self.assertGreater(len(self.rows), 20)
        for row in self.rows:
            self.assertEqual(len(row), 3, row)
            self.assertRegex(row[2], r'`test_\w+\.\w+\.test_\w+`', row[0])

    def test_every_test_the_table_names_exists(self):
        for row in self.rows:
            for module, case, test in re.findall(r'`(test_\w+)\.(\w+)\.(test_\w+)`', row[2]):
                case_class = getattr(importlib.import_module('main.tests.' + module), case, None)
                self.assertTrue(callable(getattr(case_class, test, None)), '{}.{}.{}'.format(module, case, test))

    def test_every_key_a_team_may_set_has_a_row_and_every_key_named_is_one(self):
        named = {key for row in self.rows for key in re.findall(r'`([A-Z][A-Z_]+)`', row[1])}
        self.assertEqual(named, {key.name for key in fields(ReportSettings)})

from django.test import Client, TestCase
from django.utils import timezone

from main.models import DoAvailable

from datetime import datetime, timedelta
from unittest.mock import patch


class DoBasicTestCase(TestCase):
    def assertDoYearStarts(self, year, month, day):
        date = DoAvailable.year_start(year)
        self.assertEqual(date.month, month)
        self.assertEqual(date.day, day)

    def test_historical_year_start(self):
        # Test that we're maintaining consistency with history
        self.assertDoYearStarts(2004, 1, 6)
        self.assertDoYearStarts(2005, 1, 4)
        self.assertDoYearStarts(2006, 1, 3)
        self.assertDoYearStarts(2007, 1, 2)
        self.assertDoYearStarts(2008, 1, 1)
        self.assertDoYearStarts(2009, 1, 6)
        self.assertDoYearStarts(2010, 1, 5)
        self.assertDoYearStarts(2011, 1, 4)
        self.assertDoYearStarts(2012, 1, 3)
        self.assertDoYearStarts(2013, 1, 1)
        self.assertDoYearStarts(2014, 12, 31)
        self.assertDoYearStarts(2015, 12, 30)
        self.assertDoYearStarts(2016, 12, 29)
        self.assertDoYearStarts(2017, 12, 27)
        self.assertDoYearStarts(2018, 12, 26)
        self.assertDoYearStarts(2019, 12, 25)
        self.assertDoYearStarts(2020, 12, 31)
        self.assertDoYearStarts(2021, 12, 29)

    def test_shifts(self):
        shifts = [(y, q, w)
                  for y in range(2004, 2100)
                  for q in range(1, 5)
                  for w in range(1, DoAvailable.num_weeks_in_quarter(y, q)+1)]

        for shift, next_shift in zip(shifts, shifts[1:]):
            shift_start = DoAvailable.shift_start(shift[0], shift[1], shift[2])
            self.assertEqual(shift_start.weekday(), 1)

            shift_end = DoAvailable.shift_end(shift[0], shift[1], shift[2])
            next_shift_start = DoAvailable.shift_start(next_shift[0], next_shift[1], next_shift[2])
            self.assertEqual(shift_end, next_shift_start - timedelta(minutes=1))


    def check_current(self, dt, year, quarter, week):
        with patch.object(timezone, 'now', return_value=dt):
            self.assertEquals(DoAvailable.current_year(), year)
            self.assertEquals(DoAvailable.current_quarter(), quarter)
            self.assertEquals(DoAvailable.current_week(), week)

    def test_current(self):
        # Check that some dates would show the correct y,q,w
        self.check_current(datetime(2020, 4, 1), 2020, 2, 1)
        self.check_current(datetime(2020, 1, 1), 2020, 1, 1)
        self.check_current(datetime(2019, 12, 25), 2019, 4, 14)
        self.check_current(datetime(2018, 12, 31), 2019, 1, 1)
        self.check_current(datetime(2012, 1, 1), 2011, 4, 13)

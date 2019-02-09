"""
Tests for log in workflows
Usage: python3 -m pytest main/tests/selenium_tests/test_poc.py
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from browser_helpers import BrowserHelper
from pages.login_page import LoginPage
from pages.main_page import MainPage
from pages.events_page import EventsPage

class TestLogIn():
    """
    Test for log in flows
    """
    @classmethod
    def setup_class(cls):
        """
        Loads the browser with the needed arguments
        """
        print("Starting class: {} execution".format(cls.__name__))
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        cls.driver = webdriver.Chrome(chrome_options=chrome_options)
        cls.driver.fullscreen_window()

    @classmethod
    def teardown_class(cls):
        cls.driver.quit()

    @staticmethod
    def test_log_in_success():
        driver = TestLogIn.driver
        LoginPage(driver).log_in()

        # Log out to clean up session
        driver.get("https://staging.bamru.info/accounts/logout/")

    @staticmethod
    def test_add_delete_event():
        driver = TestLogIn.driver
        helpers = BrowserHelper(driver)
        event_title = "Test title 123 !@#"

        LoginPage(driver).log_in()
        main_page = MainPage(driver)
        main_page.click_events_in_top_nav()
        events_page = EventsPage(driver)
        events_page.click_new_event_btn()
        events_page.fill_out_event_title(event_title)
        events_page.fill_out_event_description("Test description")
        events_page.select_event_type("Training")
        events_page.fill_out_event_location("Redwood City, CA")
        events_page.fill_out_event_leaders("John Chang")
        events_page.click_update_btn()

        # Assert correct values
        # TODO(gene): We can probably check for more stuff here
        subhead_selector = {"by": By.CLASS_NAME, "value": "subhead"}
        subhead_element = helpers.find_element(subhead_selector)
        helpers.text_present_in_element(subhead_selector, event_title)

        # Check that the event appears in the events page
        main_page.click_events_in_top_nav()
        events_page.confirm_event_in_table("Upcoming", event_title)
        events_page.click_on_event_in_table("Upcoming", event_title)

        # Delete event to clean up
        events_page.click_delete()
        driver.switch_to.alert.accept()

        # Confirm the event was removed from table
        events_page.confirm_event_not_in_table("Upcoming", event_title)

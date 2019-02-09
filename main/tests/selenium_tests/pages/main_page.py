"""
Main page
"""
from selenium.webdriver.common.by import By
from browser_helpers import BrowserHelper

class MainPage():

    # Selector dictionaries
    _top_nav = {"by": By.ID, "value": "navTopLevel"}
    _events_link = {"by": By.XPATH, "value": "//a[contains(.,'Events')]"}

    def __init__(self, driver):
        self.driver = driver

    def click_events_in_top_nav(self):
        helpers = BrowserHelper(self.driver)
        top_nav_element = helpers.find_element(self._top_nav)
        helpers.click_element_in(self._events_link, top_nav_element)

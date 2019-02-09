"""
Log in page
"""
import os
from configparser import ConfigParser
from selenium.webdriver.common.by import By
from browser_helpers import BrowserHelper

class LoginPage():
    """
    Page for the UI of the Login tool
    """

    # Selector dictionaries
    _log_in_field = {"by": By.ID, "value": "id_username"}
    _password_field = {"by": By.ID, "value": "id_password"}
    _log_in_btn = {"by": By.XPATH, "value": "//button[.='Login']"}

    def __init__(self, driver):
        self.driver = driver
        driver.get("https://staging.bamru.info/")

    def log_in(self):
        """
        Log in to the BAMRU app
        """
        username = os.environ.get("BAMRU_USERNAME")
        password = os.environ.get("BAMRU_PASSWORD")

        helpers = BrowserHelper(self.driver)
        username_element = helpers.find_element(self._log_in_field)
        password_element = helpers.find_element(self._password_field)
        helpers.fill_in(username_element, username)
        print(username)
        helpers.fill_in(password_element, password)
        submit_btn = helpers.click_element(self._log_in_btn)
        helpers.find_element({"by": By.CLASS_NAME, "value": "btn-group-vertical"})

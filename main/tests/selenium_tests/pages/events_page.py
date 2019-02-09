"""
Events page
"""
from selenium.webdriver.common.by import By
from browser_helpers import BrowserHelper

class EventsPage():

    # Selector dictionaries
    _new_event = {"by": By.CLASS_NAME, "value": "fa-calendar-plus-o"}
    _title_field = {"by": By.ID, "value": "id_title"}
    _description_field = {"by": By.ID, "value": "id_description"}
    _location_field = {"by": By.ID, "value": "id_location"}
    _type_field = {"by": By.ID, "value": "id_type"}
    _leaders_field = {"by": By.ID, "value": "id_leaders"}
    _update_btn = {"by": By.XPATH, "value": "//input[@value='Update']"}
    _delete_btn = {"by": By.CLASS_NAME, "value": "fa-trash"}

    def __init__(self, driver):
        self.helpers = BrowserHelper(driver)

    def click_new_event_btn(self):
        self.helpers.click_element(self._new_event)

    def fill_out_event_title(self, title_text):
        title_field_element = self.helpers.find_element(self._title_field)
        self.helpers.fill_in(title_field_element, title_text)

    def fill_out_event_description(self, description_text):
        description_field_element = self.helpers.find_element(self._description_field)
        self.helpers.fill_in(description_field_element, description_text)

    def select_event_type(self, event_type):
        type_field_element = self.helpers.find_element(self._type_field)
        self.helpers.select_from_dropdown(type_field_element, event_type)

    def fill_out_event_location(self, location_text):
        location_field_element = self.helpers.find_element(self._location_field)
        self.helpers.fill_in(location_field_element, location_text)

    def fill_out_event_leaders(self, leaders_text):
        leaders_field_element = self.helpers.find_element(self._leaders_field)
        self.helpers.fill_in(leaders_field_element, leaders_text)

    def click_update_btn(self):
        self.helpers.click_element(self._update_btn)

    def click_delete(self):
        self.helpers.click_element(self._delete_btn)

    def confirm_event_in_table(self, table, event):
        event_xpath = "//table[@id='{}']//a[.='{}']".format(table, event)
        self.helpers.find_element({"by": By.XPATH, "value": event_xpath})

    def confirm_event_not_in_table(self, table, event):
        event_xpath = "//table[@id='{}']//a[.='{}']".format(table, event)
        self.helpers.wait_to_disappear({"by": By.XPATH, "value": event_xpath})

    def click_on_event_in_table(self, table, event):
        event_xpath = "//table[@id='{}']//a[.='{}']".format(table, event)
        self.helpers.click_element({"by": By.XPATH, "value": event_xpath})

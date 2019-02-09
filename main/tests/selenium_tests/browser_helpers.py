"""
Common helpers
"""
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select as WebDriverSelect

TIMEOUT = 20

class BrowserHelper(object):
    """
    Helper function to interact with the browser
    """
    def __init__(self, driver):
        self.driver = driver

    def find_element(self, locator_dict, timeout=TIMEOUT):
        """
        Return element after it is visible
        """
        WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((locator_dict.get("by"), locator_dict.get("value"))))
        return self.driver.find_element(locator_dict.get("by"), locator_dict.get("value"))

    def find_elements(self, locator_dict, timeout=TIMEOUT):
        """
        Return a list of elements
        """
        WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_elements_located((locator_dict.get("by"), locator_dict.get("value"))))
        return self.driver.find_elements(locator_dict.get("by"), locator_dict.get("value"))

    def click_element(self, locator_dict, timeout=TIMEOUT):
        """
        Click on element once visible
        """
        WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((locator_dict.get("by"), locator_dict.get("value")))).click()

    def click_element_in(self, locator_dict, element, timeout=TIMEOUT):
        """
        Click element within given element
        """
        WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((locator_dict.get("by"), locator_dict.get("value"))))
        element.find_element(locator_dict.get("by"), locator_dict.get("value")).click()

    def wait_to_disappear(self, locator_dict, timeout=TIMEOUT):
        """
        Wait until element is invisible
        """
        WebDriverWait(self.driver, timeout).until(
            EC.invisibility_of_element_located((locator_dict.get("by"), locator_dict.get("value"))))

    def text_present_in_element(self, locator_dict, text, timeout=TIMEOUT):
        """
        Confirm text is present in element
        """
        WebDriverWait(self.driver, timeout).until(EC.text_to_be_present_in_element((
            locator_dict.get("by"), locator_dict.get("value")), text))

    def text_not_present_in_element(self, locator_dict, text, timeout=TIMEOUT):
        """
        Confirm text is present in element
        """
        WebDriverWait(self.driver, timeout).until(not EC.text_to_be_present_in_element((
            locator_dict.get("by"), locator_dict.get("value")), text))

    @classmethod
    def fill_in(cls, element, value):
        """
        Fill in element with the given value
        """
        element.clear()
        element.send_keys(value)

    @classmethod
    def select_from_dropdown(cls, dropdown_element, value):
        """
        Select a given value from the given dropdown_element
        """
        select_list = WebDriverSelect(dropdown_element)
        select_list.select_by_visible_text(value)

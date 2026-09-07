"""TheApp Login screen page object (demonstrates the POM pattern).

The selectors below are the accessibility ids exposed by TheApp's login
screen (``username``, ``password``, ``loginBtn`` - the app maps both
``testID`` and ``accessibilityLabel`` to those values).

The invalid-credentials alert shows how *genuinely platform-specific*
selectors are handled: both platforms display a native alert, but it can
only be queried via platform locators (Android ``resource-id`` XPath vs
iOS NSPredicate).
"""

from __future__ import annotations

from appium.webdriver.common.appiumby import AppiumBy

from pages.base_page import BasePage


class LoginPage(BasePage):
    """Login form: two text fields and a Login button."""

    # -- shared locators (accessibility ids, both platforms) ----------- #
    USERNAME_FIELD = "username"
    PASSWORD_FIELD = "password"
    LOGIN_BUTTON = "loginBtn"

    # -- platform-specific alert locators (native alerts differ) ------- #
    ALERT_TEXT_LOCATORS = {
        "android": (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='android:id/message']"),
        "ios": (AppiumBy.IOS_PREDICATE, "label CONTAINS 'Invalid login credentials'"),
    }
    ALERT_OK_BUTTON_LOCATORS = {
        "android": (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/button1']"),
        "ios": (AppiumBy.IOS_PREDICATE, "type == 'XCUIElementTypeButton' AND label == 'OK'"),
    }

    # -- low-level actions ---------------------------------------------- #
    def enter_username(self, username: str) -> "LoginPage":
        self.type_text(self.USERNAME_FIELD, username)
        return self

    def enter_password(self, password: str) -> "LoginPage":
        self.type_text(self.PASSWORD_FIELD, password)
        return self

    def tap_login(self) -> "LoginPage":
        # The soft keyboard can cover the Login button on small screens:
        # hide it first (no-op when it is not shown).
        self.hide_keyboard()
        self.click(self.LOGIN_BUTTON)
        return self

    # -- business-level actions ----------------------------------------- #
    def login_success(self, username: str, password: str) -> "SecretPage":
        """Log in with valid credentials and wait for the Secret screen."""
        from pages.secret_page import SecretPage  # local import avoids cycles

        self.log.info("Logging in (valid credentials)", kv={"username": username})
        self.enter_username(username).enter_password(password).tap_login()
        secret_page = SecretPage(self.driver, self.settings)
        secret_page.wait_logged_in_as(username)
        return secret_page

    def login_invalid(self, username: str, password: str) -> str:
        """Log in with invalid credentials; return the alert message text.

        The alert is left open - call :meth:`dismiss_alert` afterwards.
        """
        self.log.info("Logging in (invalid credentials)", kv={"username": username})
        self.enter_username(username).enter_password(password).tap_login()
        by, value = self.ALERT_TEXT_LOCATORS[self.platform]
        alert_element = self.wait_for_element((by, value))
        message = self.get_text_element(alert_element)
        self.log.info("Invalid-credentials alert shown", kv={"message": message})
        return message

    def dismiss_alert(self) -> "LoginPage":
        """Tap the alert's OK button (platform-aware)."""
        by, value = self.ALERT_OK_BUTTON_LOCATORS[self.platform]
        self.wait_for_element((by, value)).click()
        return self

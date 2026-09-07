"""TheApp "Secret Area" screen page object (shown after a successful login).

The logged-in username is rendered inside an element whose accessibility id
is ``Logged in as <username>`` - a useful pattern for assertions.
"""

from __future__ import annotations

from appium.webdriver.common.appiumby import AppiumBy

from pages.base_page import BasePage


class SecretPage(BasePage):
    """Post-login screen (only reachable with valid credentials)."""

    # Platform-specific locator for the Logout button: this button has no
    # accessibility id in TheApp, so we fall back to platform selectors.
    LOGOUT_BUTTON_LOCATORS = {
        "android": (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Logout")'),
        "ios": (AppiumBy.IOS_PREDICATE, "name == 'Logout'"),
    }

    # ------------------------------------------------------------------ #
    def logged_in_as_element(self, username: str):
        """The element whose accessibility id proves the login state."""
        return self.wait_for_element(f"Logged in as {username}")

    def wait_logged_in_as(self, username: str):
        """Block until the Secret screen shows the given user."""
        self.wait_for_element(f"Logged in as {username}")
        self.log.info("Confirmed logged-in state", kv={"username": username})
        return self

    def is_logged_in_as(self, username: str) -> bool:
        """Quick, non-blocking check of the logged-in state."""
        return self.is_visible(f"Logged in as {username}")

    # ------------------------------------------------------------------ #
    def logout(self) -> "LoginPage":
        """Tap Logout and return to the Login screen."""
        from pages.login_page import LoginPage  # local import avoids cycles

        by, value = self.LOGOUT_BUTTON_LOCATORS[self.platform]
        self.wait_for_element((by, value)).click()
        login_page = LoginPage(self.driver, self.settings)
        login_page.wait_for_element(LoginPage.USERNAME_FIELD)
        return login_page

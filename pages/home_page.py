"""TheApp home screen page object.

TheApp (https://github.com/appium-pro/TheApp) is the free demo application
used by the sample tests: it is cross-platform and exposes stable
accessibility ids. Swap these locators for YOUR app's screens.
"""

from __future__ import annotations

from pages.base_page import BasePage


class HomePage(BasePage):
    """The launch screen: a list of available demo screens."""

    # -- locators ------------------------------------------------------- #
    LOGIN_SCREEN_ROW = "Login Screen"
    ECHO_BOX_ROW = "Echo Box"
    LIST_DEMO_ROW = "List Demo"

    # -- actions -------------------------------------------------------- #
    def navigate_to_login(self) -> "LoginPage":
        """Open the Login screen and wait until it is ready."""
        from pages.login_page import LoginPage  # local import avoids cycles

        self.log.info("Navigating to the Login screen")
        self.wait_for_element(self.LOGIN_SCREEN_ROW)
        self.click(self.LOGIN_SCREEN_ROW)
        login_page = LoginPage(self.driver, self.settings)
        login_page.wait_for_element(LoginPage.USERNAME_FIELD)  # screen ready
        return login_page

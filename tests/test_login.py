"""Sample tests: TheApp login flow (Android + iOS).

TheApp (https://github.com/appium-pro/TheApp) is a free cross-platform test
application. Its login screen accepts the demo credentials below and shows
a "Secret Area" screen after a successful login.

REPLACE BEFORE USE IN YOUR PROJECT
----------------------------------
* swap ``HomePage``/``LoginPage``/``SecretPage`` usage for YOUR pages;
* the demo credentials belong to TheApp only - manage your own test
  accounts in config or an env file;
* nothing here is platform-specific: the same test runs against Android
  and iOS via ``--platform`` / ``APP_PLATFORM``.

Platform gating (when you DO need it) looks like::

    import os
    needs_android = pytest.mark.skipif(
        os.environ.get("APP_PLATFORM") != "android", reason="Android only")
"""

from __future__ import annotations

import pytest

from pages.home_page import HomePage

# Demo accounts baked into TheApp (replace with your own test data source):
VALID_USERNAME = "alice"      # CHANGE ME -> YOUR_TEST_USER
VALID_PASSWORD = "mypassword"  # CHANGE ME -> YOUR_TEST_PASSWORD
INVALID_USERNAME = "nobody"
INVALID_PASSWORD = "wrong-password"

pytestmark = pytest.mark.login


class TestTheAppLogin:
    """Happy path + negative path for the login screen."""

    def test_valid_credentials_reach_secret_area(self, driver):
        """Home -> Login Screen -> valid login -> Secret Area badge shown."""
        secret_page = (
            HomePage(driver)
            .navigate_to_login()
            .login_success(username=VALID_USERNAME, password=VALID_PASSWORD)
        )
        # TheApp renders an element with accessibility id "Logged in as alice"
        assert secret_page.is_logged_in_as(VALID_USERNAME), (
            f"Expected the Secret Area to show the logged-in user "
            f"{VALID_USERNAME!r}"
        )

    def test_invalid_credentials_show_error_alert(self, driver):
        """Invalid credentials must surface a native alert, not log in."""
        login_page = HomePage(driver).navigate_to_login()
        message = login_page.login_invalid(username=INVALID_USERNAME, password=INVALID_PASSWORD)

        assert "Invalid login credentials" in message, f"Unexpected alert text: {message!r}"

        # Dismiss the alert and assert we are still on the login screen
        login_page.dismiss_alert()
        assert login_page.is_visible(login_page.USERNAME_FIELD), (
            "Expected to remain on the login screen after dismissing the alert"
        )

    def test_logout_returns_to_login_screen(self, driver):
        """Logged-in users can log out again (text-based platform locators)."""
        login_page = (
            HomePage(driver)
            .navigate_to_login()
            .login_success(username=VALID_USERNAME, password=VALID_PASSWORD)
            .logout()
        )
        assert login_page.is_visible(login_page.USERNAME_FIELD)

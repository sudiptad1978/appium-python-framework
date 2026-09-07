"""Driver factory: single entry point for creating Android/iOS drivers.

* decides Android vs iOS purely from configuration (never from test code);
* performs a fast health check against the Appium server *before* a session
  request, so "server is down" and "session failed" are two distinct,
  actionable errors;
* wraps session-creation failures with context-rich messages that point at
  the real causes (device not connected, driver not installed, app path
  wrong) - including the Appium server log location.
"""

from __future__ import annotations

import socket
from typing import Optional

from appium import webdriver
from selenium.common.exceptions import WebDriverException

from drivers.options_builder import build_options
from utils.appium_server import fetch_status
from utils.config_reader import Settings
from utils.errors import DriverInitializationError
from utils.logger import get_logger

LOG = get_logger("driver_factory")


class DriverFactory:
    """Creates (and quits) Appium WebDriver sessions from :class:`Settings`."""

    def __init__(self, settings: Settings):
        self._settings = settings

    # ------------------------------------------------------------------ #
    @property
    def settings(self) -> Settings:
        return self._settings

    def server_url(self) -> str:
        return self._settings.server_url()

    def check_server(self) -> Optional[dict]:
        """Return the /status payload when an Appium server is reachable."""
        return fetch_status(self._settings.health_url(), timeout=2.0)

    # ------------------------------------------------------------------ #
    def create_driver(self):
        """Create a session for the configured platform and return the driver.

        Raises:
            DriverInitializationError: with a diagnostic message when the
                server is down, the capabilities are invalid, or Appium
                rejects the session request.
        """
        settings = self._settings
        url = self.server_url()

        LOG.info("Creating driver", kv={"platform": settings.platform, "url": url, "summary": settings.summary()})

        # 1) Fast, explicit server availability check
        status = self.check_server()
        if status is None:
            raise DriverInitializationError(
                f"No Appium server reachable at {url}. Check that:\n"
                f"  * config/settings.yaml points at the right host/port;\n"
                f"  * auto_start is enabled or an external server is running;\n"
                f"  * the server log {settings.log_dir / 'appium_server.log'} (if any) shows no errors."
            )
        LOG.info("Appium server reachable", kv={"url": url})

        # 2) Build and validate capabilities (fast, local feedback)
        try:
            options = build_options(settings)
        except Exception as exc:
            raise DriverInitializationError(f"Invalid capabilities: {exc}") from exc

        LOG.debug("Session capabilities", kv={"caps": options.to_capabilities()})

        # 3) Create the session
        try:
            driver = webdriver.Remote(url, options=options)
        except WebDriverException as exc:
            message = str(exc)
            hints = self._diagnose_failure(message)
            raise DriverInitializationError(
                f"Appium could not create a {settings.platform} session at {url}.\n"
                f"Server response: {message[:500]}\n{hints}"
            ) from exc
        except Exception as exc:  # e.g. DNS/connection errors mid-handshake
            raise DriverInitializationError(
                f"Unexpected error while creating the {settings.platform} session: {exc}"
            ) from exc

        LOG.info(
            "Driver created successfully",
            kv={
                "session_id": getattr(driver, "session_id", "?"),
                "platform": settings.platform,
                "desired": settings.device.get("device_name"),
            },
        )
        return driver

    # ------------------------------------------------------------------ #
    def quit_driver(self, driver) -> None:
        """Safely end a session (never raises)."""
        if driver is None:
            return
        try:
            driver.quit()
            LOG.info("Driver session closed")
        except WebDriverException as exc:
            LOG.warning("Error while quitting driver (already gone?)", kv={"reason": str(exc)[:200]})

    # ------------------------------------------------------------------ #
    @staticmethod
    def _diagnose_failure(message: str) -> str:
        lowered = (message or "").lower()
        hints = ["Possible causes and fixes:"]
        if any(word in lowered for word in ("not installed", "driver", "could not be found", "unknown driver")):
            hints.append(
                "  * the Appium driver is not installed - run "
                "'appium driver install uiautomator2' (Android) / "
                "'appium driver install xcuitest' (iOS)"
            )
        if "device" in lowered or "emulator" in lowered or "simulator" in lowered:
            hints.append(
                "  * no device/emulator/simulator is connected - check "
                "'adb devices' (Android) / 'xcrun simctl list devices' (iOS)"
            )
        if "app" in lowered or "apk" in lowered or "bundle" in lowered:
            hints.append("  * the app path / package / bundle id may be wrong (config/<platform>.yaml)")
        if "no such file" in lowered or "file not found" in lowered:
            hints.append("  * the app binary does not exist on this machine")
        hints.append("  * full details are in the Appium server log (logs/appium_server.log)")
        return "\n".join(hints)


def create_driver(settings: Settings):
    """Module-level convenience wrapper around :class:`DriverFactory`."""
    return DriverFactory(settings).create_driver()

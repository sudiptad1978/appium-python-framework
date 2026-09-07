"""Builds Appium 2.x W3C capability objects from the platform YAML files.

Why an options builder?
-----------------------
* Capability keys follow the W3C standard: ``platformName`` is a standard
  capability; everything Appium-specific is namespaced with the
  ``appium:`` prefix (``appium:automationName``, ``appium:appPackage``...).
  Modern Appium *ignores* unprefixed custom capabilities - the builder
  guarantees the prefixing is always right.
* ``UiAutomator2Options`` / ``XCUITestOptions`` (the Appium Python client's
  typed option classes) validate and serialize the map; they are the
  recommended replacement for the removed ``desired_capabilities`` dicts.
* All validation happens *before* a session request is made, so the error
  messages point at the exact config value to fix (app path missing,
  device name missing, ...).
"""

from __future__ import annotations

from pathlib import Path

from appium.options.android import UiAutomator2Options
from appium.options.common.base import AppiumOptions
from appium.options.ios import XCUITestOptions

from utils.config_reader import Settings
from utils.errors import ConfigError, DriverInitializationError

# Base capabilities shared by both platforms. ``platformName`` stays
# unprefixed (W3C); all Appium extension caps carry the ``appium:`` prefix.
def _common_capabilities(settings: Settings) -> dict:
    device = settings.device
    capabilities = {
        "platformName": device.get("platform_name"),  # Android / iOS
        "appium:automationName": device.get("automation_name"),  # UiAutomator2 / XCUITest
        "appium:deviceName": str(device.get("device_name") or ""),
    }
    udid = str(device.get("udid") or "").strip()
    if udid:
        capabilities["appium:udid"] = udid

    no_reset = device.get("no_reset", True)
    full_reset = device.get("full_reset", False)
    capabilities["appium:noReset"] = bool(no_reset)
    if full_reset:
        capabilities["appium:fullReset"] = True

    # App under test: either an explicit path or the already-installed app
    app_path = settings.resolve_app_path()
    if app_path:
        if not Path(app_path).exists():
            raise ConfigError(
                f"App binary not found: {app_path}\n"
                f"Point app_path in config/{settings.platform}.yaml at YOUR app "
                f"(or set the APP_PATH environment variable) and try again."
            )
        capabilities["appium:app"] = app_path
    return capabilities


def _platform_capabilities(settings: Settings) -> dict:
    """Platform-specific capabilities (package/activity vs bundle id)."""
    device = settings.device
    capabilities: dict = {}
    additional = dict(device.get("additional_capabilities") or {})

    if settings.platform == "android":
        capabilities.update(
            {
                "appium:appPackage": str(device.get("app_package") or ""),
                "appium:appActivity": str(device.get("app_activity") or ""),
            }
        )
        if device.get("auto_grant_permissions", False):
            capabilities["appium:autoGrantPermissions"] = True
        if not capabilities.get("appium:app") and not capabilities["appium:appPackage"]:
            raise ConfigError(
                "Android config is incomplete: set app_path (a .apk) or "
                "app_package + app_activity (installed app) in config/android.yaml."
            )
    else:  # ios
        bundle_id = str(device.get("bundle_id") or "")
        if bundle_id:
            capabilities["appium:bundleId"] = bundle_id
        if device.get("auto_accept_alerts", False):
            capabilities["appium:autoAcceptAlerts"] = True
        # Real-device signing (optional, only meaningful on physical iPhones)
        for key in ("xcodeOrgId", "xcodeSigningId"):
            value = device.get(key) or device.get(key[0].lower() + key[1:])
            if value:
                capabilities[f"appium:{key}"] = str(value)
        if not capabilities.get("appium:app") and not bundle_id:
            raise ConfigError(
                "iOS config is incomplete: set app_path (a .app/.zip/.ipa) or "
                "bundle_id (installed app) in config/ios.yaml."
            )

    # User-defined extras win over the defaults above
    capabilities.update(additional)
    return capabilities


def _validate_device(settings: Settings) -> None:
    """A device must be addressable: by name, by udid, or (Android) the
    default emulator serial."""
    device = settings.device
    has_name = bool(str(device.get("device_name") or "").strip())
    has_udid = bool(str(device.get("udid") or "").strip())
    if settings.platform == "ios" and not has_name and not has_udid:
        raise ConfigError(
            "iOS config needs a device: set device_name (simulator name) or "
            "udid in config/ios.yaml."
        )
    if settings.platform == "android" and not has_name and not has_udid:
        raise ConfigError(
            "Android config needs a device: set device_name (adb serial, e.g. "
            "'emulator-5554') or udid in config/android.yaml."
        )


def build_options(settings: Settings) -> AppiumOptions:
    """Return the typed options object for the configured platform."""
    _validate_device(settings)
    capabilities = _common_capabilities(settings)
    capabilities.update(_platform_capabilities(settings))

    if settings.platform == "android":
        return UiAutomator2Options().load_capabilities(capabilities)
    return XCUITestOptions().load_capabilities(capabilities)


def describe_capabilities(settings: Settings) -> dict:
    """Human-readable capability summary for logs (paths shortened)."""
    options = build_options(settings)
    caps = options.to_capabilities()
    return {key: value for key, value in caps.items() if value not in ("", None)}


# Re-export so factory/tests import one name:
class CapabilityBuilderError(DriverInitializationError):  # backward-compat alias
    pass

"""Framework-wide exception types.

Keeping them in one place avoids circular imports and gives tests a single
set of exceptions they can catch/treat in a custom way.
"""


class FrameworkError(RuntimeError):
    """Base class for all framework errors."""


class ConfigError(FrameworkError):
    """Raised when configuration files/env/CLI are missing or invalid."""


class AppiumServerError(FrameworkError):
    """Raised when the Appium server cannot be started/stopped/reached."""


class DriverInitializationError(FrameworkError):
    """Raised when a WebDriver session cannot be created.

    The message is intentionally verbose: it points the user at the most
    common causes (device not connected, app path wrong, drivers missing).
    """


class GestureNotSupportedError(FrameworkError, NotImplementedError):
    """Raised when a gesture is not available on the current platform."""


class ElementNotFoundError(FrameworkError):
    """Raised by scroll-to-element helpers when the target never appears."""


class WaitTimeoutError(FrameworkError, TimeoutError):
    """Raised by custom wait helpers when the condition did not become true."""

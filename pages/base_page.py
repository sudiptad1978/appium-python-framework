"""BasePage: the toolbox every page object inherits.

Implements the shared, driver-level actions the framework promises:

* find / click / enter text / read text
* explicit waits (visible, gone, clickable, text)
* visibility checks (non-blocking)
* gestures (swipe/scroll delegates into :mod:`utils.gestures`)
* screenshots

Conventions
-----------
* **Locators** are either a plain string (interpreted as an
  *accessibility id* - the most robust locator on both Android and iOS) or a
  ``(AppiumBy.X, value)`` tuple for anything else:

  .. code-block:: python

      element = self.find_element("login_btn")                      # by accessibility id
      element = self.find_element(AppiumBy.XPATH, "//android.widget.Button[@text='OK']")
      element = self.find_element(AppiumBy.IOS_PREDICATE, "label BEGINSWITH 'Log'")

* Page methods **wait before they act** (explicit waits, never sleep).
* Anything that can fail with a timeout produces a
  :class:`~utils.errors.WaitTimeoutError`; the global pytest hook saves a
  screenshot + page source automatically on failure.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple, Union

from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.remote.webelement import WebElement

import utils.gestures as gestures
import utils.waits as waits
from utils.config_reader import PROJECT_ROOT, Settings
from utils.logger import get_logger
from utils.screenshot import save_page_source, save_screenshot

Locator = Union[str, Tuple[Any, str]]


class BasePage:
    """Shared page-object base class.

    Args:
        driver: the active Appium driver (from the ``driver`` fixture).
        settings: optional resolved settings (used for artifact paths and
            default timeouts). Tests can simply pass ``driver``; the
            defaults match ``config/settings.yaml``.
    """

    def __init__(self, driver, settings: Optional[Settings] = None):
        self.driver = driver
        self.settings = settings
        self.log = get_logger(f"pages.{type(self).__name__}")

        if settings is not None:
            self._screenshot_dir = settings.screenshot_dir
            self._page_source_dir = settings.page_source_dir
            self._default_timeout = settings.timeout_default
        else:
            self._screenshot_dir = PROJECT_ROOT / "artifacts" / "screenshots"
            self._page_source_dir = PROJECT_ROOT / "artifacts" / "page_source"
            self._default_timeout = 15

        self.platform = gestures.detect_platform(driver)

    # ------------------------------------------------------------------ #
    # locator helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_locator(by: Locator, value=None) -> tuple:
        if value is None:
            if isinstance(by, (tuple, list)) and len(by) == 2:
                return tuple(by)
            return (AppiumBy.ACCESSIBILITY_ID, by)  # plain string => accessibility id
        return (by, value)

    def _timeout(self, timeout: Optional[float]) -> float:
        return self._default_timeout if timeout is None else timeout

    # ------------------------------------------------------------------ #
    # finding & waiting
    # ------------------------------------------------------------------ #
    def find_element(self, by: Locator, value=None, timeout: Optional[float] = None) -> WebElement:
        """Wait for the element to exist, then return it (no visibility req.)."""
        return waits.wait_for_presence(
            self.driver, *self._to_locator(by, value), timeout=self._timeout(timeout)
        )

    def wait_for_element(self, by: Locator, value=None, timeout: Optional[float] = None) -> WebElement:
        """Wait until the element is visible and return it (recommended)."""
        return waits.wait_for_visibility(
            self.driver, *self._to_locator(by, value), timeout=self._timeout(timeout)
        )

    def wait_until_gone(self, by: Locator, value=None, timeout: Optional[float] = None) -> bool:
        """Wait until the element disappears (splash, spinner, dialog)."""
        return waits.wait_for_invisibility(
            self.driver, *self._to_locator(by, value), timeout=self._timeout(timeout)
        )

    def wait_for_text(self, by: Locator, expected_text: str, value=None, timeout: Optional[float] = None) -> bool:
        """Wait until the element's text contains ``expected_text``."""
        return waits.wait_for_text(
            self.driver, *self._to_locator(by, value), expected_text, timeout=self._timeout(timeout)
        )

    def is_visible(self, by: Locator, value=None) -> bool:
        """Non-blocking check: does the element exist AND is it displayed?"""
        return waits.is_element_visible(self.driver, *self._to_locator(by, value))

    def is_present(self, by: Locator, value=None) -> bool:
        """Non-blocking check: does the element exist at all?"""
        return waits.is_element_present(self.driver, *self._to_locator(by, value))

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #
    def click_element(self, element: WebElement) -> None:
        """Click an already-resolved element (waits for clickability first)."""
        waits.wait_for_clickable(
            self.driver, (AppiumBy.ID, element.id), timeout=self._timeout(None)
        )
        element.click()
        self.log.debug("Clicked element", kv={"element_id": element.id})

    def click(self, by: Locator, value=None, timeout: Optional[float] = None) -> None:
        """Find (visible) and click. The workhorse of page objects."""
        locator = self._to_locator(by, value)
        element = waits.wait_for_clickable(self.driver, *locator, timeout=self._timeout(timeout))
        element.click()
        self.log.debug("Clicked element", kv={"locator": (locator[0], str(locator[1]))})

    def tap(self, by: Locator, value=None, timeout: Optional[float] = None) -> None:
        """Tap the centre of an element via a W3C pointer gesture.

        Prefer ``click()`` for regular buttons; use ``tap()`` when the
        native click does not register (known iOS quirks with certain
        custom views).
        """
        element = self.wait_for_element(by, value, timeout=timeout)
        gestures.tap_element(self.driver, element)

    def type_text(
        self,
        by: Locator,
        text: str,
        value=None,
        clear_first: bool = True,
        timeout: Optional[float] = None,
    ) -> None:
        """Tap the field, optionally clear it, then type ``text``.

        The element is located by an explicit visibility wait; the typing
        itself uses native ``send_keys``.
        """
        element = self.wait_for_element(by, value, timeout=timeout)
        self.type_text_element(element, text, clear_first=clear_first)

    def type_text_element(self, element: WebElement, text: str, clear_first: bool = True) -> None:
        element.click()  # focus the field (shows the keyboard when needed)
        if clear_first:
            try:
                element.clear()
            except Exception:
                # Some custom views have no native clear - select-all + delete
                self.log.debug("element.clear() not supported; skipping")
        element.send_keys(text)
        self.log.debug("Entered text", kv={"characters": len(text), "element_id": element.id})

    def clear_text(self, by: Locator, value=None, timeout: Optional[float] = None) -> None:
        element = self.wait_for_element(by, value, timeout=timeout)
        element.clear()
        self.log.debug("Cleared element", kv={"element_id": element.id})

    def get_text(self, by: Locator, value=None, timeout: Optional[float] = None) -> str:
        """Return the visible text of an element (falls back to its label)."""
        element = self.wait_for_element(by, value, timeout=timeout)
        text = element.text
        if not text:
            text = element.get_attribute("label") or element.get_attribute("name") or ""
        self.log.debug("Read text", kv={"characters": len(text)})
        return text.strip()

    def get_text_element(self, element: WebElement) -> str:
        text = element.text
        if not text:
            text = element.get_attribute("label") or ""
        return text.strip()

    # ------------------------------------------------------------------ #
    # gestures (thin delegates into utils.gestures)
    # ------------------------------------------------------------------ #
    def swipe(self, direction: str, element: Optional[WebElement] = None, **kwargs) -> None:
        gestures.scroll(self.driver, direction, element=element, **kwargs)

    def scroll_down(self, element: Optional[WebElement] = None, **kwargs) -> None:
        """Reveal content further down the page (finger travels up)."""
        gestures.scroll_up(self.driver, element=element, **kwargs)

    def scroll_up(self, element: Optional[WebElement] = None, **kwargs) -> None:
        """Reveal content further up the page (finger travels down)."""
        gestures.scroll_down(self.driver, element=element, **kwargs)

    def scroll_to_element(
        self,
        by: Locator,
        value=None,
        direction: str = "up",
        max_swipes: int = 10,
        container: Optional[WebElement] = None,
    ) -> WebElement:
        """Repeatedly swipe until ``by/value`` is visible; then return it."""
        locator = self._to_locator(by, value)
        return gestures.scroll_to_element(
            self.driver,
            locator[0],
            locator[1],
            direction=direction,
            max_swipes=max_swipes,
            container=container,
        )

    def hide_keyboard(self, strategy: Optional[str] = None) -> None:
        """Hide the soft keyboard if visible (safe on both platforms)."""
        gestures.hide_keyboard(self.driver, strategy=strategy)

    def back(self) -> None:
        """Android system back. On iOS raise (apps use in-app navigation)."""
        gestures.back(self.driver)

    def long_press(self, by: Locator, value=None, duration_seconds: float = 1.0) -> None:
        element = self.wait_for_element(by, value)
        gestures.long_press(self.driver, element=element, duration_seconds=duration_seconds)

    def drag_and_drop(
        self,
        source: Locator,
        target: Locator,
        hold_seconds: float = 1.0,
        value=None,
        target_value=None,
    ) -> None:
        source_element = self.wait_for_element(source, value)
        target_element = self.wait_for_element(target, target_value)
        gestures.drag_and_drop(self.driver, source_element, target_element, hold_seconds=hold_seconds)

    # ------------------------------------------------------------------ #
    # artifacts & debug
    # ------------------------------------------------------------------ #
    def take_screenshot(self, name: Optional[str] = None) -> Any:
        """Save a screenshot; returns the file path. Used for deliberate
        captures (e.g. end of smoke tests) - failures are handled globally."""
        label = name or f"{type(self).__name__}"
        return save_screenshot(self.driver, self._screenshot_dir, label)

    def dump_page_source(self, name: Optional[str] = None) -> Any:
        label = name or f"{type(self).__name__}"
        return save_page_source(self.driver, self._page_source_dir, label)

    def log_tree(self, message: str = "Page state") -> None:
        """Helper for debugging: log a short summary of the visible view."""
        source = self.driver.page_source
        self.log.info(message, kv={"page_source_characters": len(source or "")})

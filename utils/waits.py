"""Explicit-wait helpers built on Selenium's ``WebDriverWait``.

Why explicit waits?
-------------------
The framework never relies on ``time.sleep``: tests either wait for a real
condition (element visible, gone, text present) or poll a custom predicate.
This makes suites fast (waits return the moment the condition is true) and
stable (no magic sleep values to tune per device).

Error handling
--------------
Every ``wait_*`` helper converts Selenium's ``TimeoutException`` into a
:class:`~utils.errors.WaitTimeoutError` whose message includes the locator,
the timeout and a hint to inspect the failure screenshot. The original
exception is preserved as ``__cause__`` so the stack trace stays intact.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from utils.errors import WaitTimeoutError
from utils.logger import get_logger

LOG = get_logger("utils.waits")

T = TypeVar("T")

DEFAULT_POLL = 0.3  # seconds between condition polls


# ---------------------------------------------------------------------------
# low-level: wait on a bare predicate (driver-independent)
# ---------------------------------------------------------------------------
def wait_until(
    condition: Callable[[], T],
    timeout: float,
    description: str = "condition",
    poll_frequency: float = DEFAULT_POLL,
) -> T:
    """Poll ``condition()`` every ``poll_frequency`` s until it returns a
    truthy value or ``timeout`` s elapse.

    Unlike Selenium's ``WebDriverWait`` this does not swallow exceptions:
    exceptions propagate immediately (useful when the *absence* of an
    exception is itself the condition being awaited).
    """
    deadline = time.monotonic() + timeout
    while True:
        result = condition()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise WaitTimeoutError(f"Timed out after {timeout}s waiting for {description}.")
        time.sleep(poll_frequency)


# ---------------------------------------------------------------------------
# element-focused helpers (locator = (by, value) tuple, e.g. (AppiumBy.ID, "x"))
# ---------------------------------------------------------------------------
def _new_wait(driver, timeout: float | None, poll_frequency: float, default: float) -> WebDriverWait:
    effective = default if timeout is None else timeout
    return WebDriverWait(driver, timeout=effective, poll_frequency=poll_frequency)


def _as_locator(by, value) -> tuple:
    if value is None and isinstance(by, (tuple, list)) and len(by) == 2:
        return tuple(by)
    return (by, value)


def _describe(locator: tuple) -> str:
    return f"({locator[0]}, {locator[1]!r})"


def wait_for_presence(
    driver,
    by,
    value=None,
    timeout: float | None = None,
    default: float = 15,
    poll_frequency: float = DEFAULT_POLL,
) -> WebElement:
    """Wait until an element exists in the (native) view hierarchy.

    Use when the element may exist but is not yet tappable/visible, e.g.
    list items that exist but are still rendering.
    """
    locator = _as_locator(by, value)
    try:
        element = _new_wait(driver, timeout, poll_frequency, default).until(
            EC.presence_of_element_located(locator)
        )
    except TimeoutException as exc:
        LOG.error("Element never became present", kv={"locator": _describe(locator), "timeout": timeout or default})
        raise WaitTimeoutError(
            f"Element {_describe(locator)} was not present after {timeout or default}s."
        ) from exc
    LOG.debug("Element present", kv={"locator": _describe(locator)})
    return element


def wait_for_visibility(
    driver,
    by,
    value=None,
    timeout: float | None = None,
    default: float = 15,
    poll_frequency: float = DEFAULT_POLL,
) -> WebElement:
    """Wait until an element exists AND is visible (non-zero size, displayed).

    This is the most common wait in the framework and the recommended default
    for page objects.
    """
    locator = _as_locator(by, value)
    try:
        element = _new_wait(driver, timeout, poll_frequency, default).until(
            EC.visibility_of_element_located(locator)
        )
    except TimeoutException as exc:
        LOG.error("Element never became visible", kv={"locator": _describe(locator), "timeout": timeout or default})
        raise WaitTimeoutError(
            f"Element {_describe(locator)} was not visible after {timeout or default}s."
        ) from exc
    LOG.debug("Element visible", kv={"locator": _describe(locator)})
    return element


def wait_for_invisibility(
    driver,
    by,
    value=None,
    timeout: float | None = None,
    default: float = 15,
    poll_frequency: float = DEFAULT_POLL,
) -> bool:
    """Wait until an element disappears from the hierarchy (or is not
    visible). Returns True on success; raises :class:`WaitTimeoutError`.

    Typical use: splash screens, progress spinners, dialogs closing.
    """
    locator = _as_locator(by, value)
    try:
        gone = _new_wait(driver, timeout, poll_frequency, default).until(
            EC.invisibility_of_element_located(locator)
        )
    except TimeoutException as exc:
        LOG.error("Element never disappeared", kv={"locator": _describe(locator), "timeout": timeout or default})
        raise WaitTimeoutError(
            f"Element {_describe(locator)} was still present after {timeout or default}s."
        ) from exc
    LOG.debug("Element gone", kv={"locator": _describe(locator)})
    return bool(gone)


def wait_for_clickable(
    driver,
    by,
    value=None,
    timeout: float | None = None,
    default: float = 15,
    poll_frequency: float = DEFAULT_POLL,
) -> WebElement:
    """Wait until an element is visible and enabled (ready for tapping)."""
    locator = _as_locator(by, value)
    try:
        element = _new_wait(driver, timeout, poll_frequency, default).until(
            EC.element_to_be_clickable(locator)
        )
    except TimeoutException as exc:
        LOG.error("Element never became clickable", kv={"locator": _describe(locator), "timeout": timeout or default})
        raise WaitTimeoutError(
            f"Element {_describe(locator)} was not clickable after {timeout or default}s."
        ) from exc
    return element


def wait_for_text(
    driver,
    by,
    value,
    expected_text: str,
    timeout: float | None = None,
    default: float = 15,
    poll_frequency: float = DEFAULT_POLL,
) -> bool:
    """Wait until the element's text attribute contains ``expected_text``."""
    locator = _as_locator(by, value)
    try:
        found = _new_wait(driver, timeout, poll_frequency, default).until(
            EC.text_to_be_present_in_element(locator, expected_text)
        )
    except TimeoutException as exc:
        LOG.error(
            "Element text never matched",
            kv={"locator": _describe(locator), "expected": expected_text, "timeout": timeout or default},
        )
        raise WaitTimeoutError(
            f"Text {expected_text!r} was not found in {_describe(locator)} "
            f"after {timeout or default}s."
        ) from exc
    return bool(found)


# ---------------------------------------------------------------------------
# non-blocking existence checks (single, immediate lookups)
# ---------------------------------------------------------------------------
def is_element_present(driver, by, value=None, attempts: int = 1) -> bool:
    """Return True if the element exists right now.

    With an implicit wait of 0 the driver performs a single lookup, so this
    is fast and safe to call in loops.
    """
    locator = _as_locator(by, value)
    for _ in range(max(1, attempts)):
        try:
            driver.find_element(*locator)
            return True
        except NoSuchElementException:
            continue
        except StaleElementReferenceException:
            continue
    return False


def is_element_visible(driver, by, value=None, attempts: int = 1) -> bool:
    """Return True if the element exists and is currently displayed."""
    locator = _as_locator(by, value)
    for _ in range(max(1, attempts)):
        try:
            return bool(driver.find_element(*locator).is_displayed())
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    return False

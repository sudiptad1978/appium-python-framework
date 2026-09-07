"""Reusable mobile gesture helpers (Android + iOS).

API philosophy
--------------
* **W3C WebDriver Actions** (Selenium ``PointerInput`` + ``/actions``
  endpoint) are the default engine: one implementation, identical behaviour
  on both drivers, deterministic timing.
* **Native ``mobile:`` shortcut commands** (``mobile: doubleClickGesture``,
  ``mobile: touchAndHold``, ``mobile: pinchOpenGesture``...) are used where
  they are the *recommended, maintained* API and give platform-optimised
  physics (e.g. Android speed-based gestures, iOS ``pinchWithScale``).

  .. deprecated:: TouchAction / MultiAction (JSONWP) were removed from both
     Appium 2 and the Python client (v4+) - this module never uses them.

Direction semantics
-------------------
Every ``swipe_*`` / ``scroll*`` method is expressed as **finger travel**:
``swipe_up`` = finger moves from a low Y to a high Y. The content therefore
moves *up* and content *further down the page* is revealed (what most people
mean by "scroll down the page"). ``swipe_down`` goes back up the page.
Horizontal gestures follow the same logic.

Coordinates are physical pixels in the viewport, exactly like
``get_window_size()`` reports them. This matches Appium on both platforms;
iOS *points* equal pixels on modern devices (1x-3x scale handled by WDA).

Platform differences worth knowing
----------------------------------
* ``back`` is Android-only (iOS has no system back; apps expose their own
  navigation buttons - tap those via page objects).
* iOS cannot long-press coordinates *or* elements below the minimum
  ``pressForDuration`` threshold; durations < 0.5s degrade into a tap.
* ``fling`` (native, velocity-driven) exists on Android only; on iOS use
  ``flick`` (fast W3C swipe) instead.
* ``double_tap`` and ``long_press`` fall back to plain W3C sequences when
  the native shortcut fails (e.g. driver versions without the command).
* ``pinch`` on iOS maps to XCUITest ``pinchWithScale``; on Android to the
  UiAutomator2 pinch gestures. Fallbacks are attempted for both.
"""

from __future__ import annotations

from typing import Any, Tuple

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.remote.command import Command
from selenium.webdriver.remote.webelement import WebElement

from utils.errors import ElementNotFoundError, GestureNotSupportedError
from utils.logger import get_logger

LOG = get_logger("utils.gestures")

# Seconds between the pointer-up of one tap and the pointer-down of the next
# in a double tap (part of the W3C fallback sequence).
_DOUBLE_TAP_PAUSE = 0.06

# Minimum long-press duration Android registers as a long click.
_ANDROID_LONG_PRESS_MS = 500


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------
def _new_touch(name: str = "touch") -> PointerInput:
    return PointerInput(interaction.POINTER_TOUCH, name)


def _dispatch(driver: Any, pointers: list[PointerInput], gesture: str, **kv: Any) -> None:
    """Send the encoded W3C action payloads of one or more pointers."""
    payloads = [pointer.encode() for pointer in pointers]
    payloads = [payload for payload in payloads if payload.get("actions")]
    if not payloads:
        LOG.warning("Gesture produced no actions; nothing dispatched", kv={"gesture": gesture})
        return
    LOG.debug("Dispatching W3C actions", kv={"gesture": gesture, "pointers": len(payloads), **kv})
    driver.execute(Command.W3C_ACTIONS, {"actions": payloads})
    LOG.info("Gesture performed", kv={"gesture": gesture, **kv})


def _mobile(driver: Any, script: str, params: dict, gesture: str, **kv: Any) -> Any:
    """Execute a native ``mobile:`` shortcut with logging."""
    LOG.debug("Executing mobile command", kv={"script": script, "params": params})
    result = driver.execute_script(script, params)
    LOG.info("Gesture performed (native)", kv={"gesture": gesture, "script": script, **kv})
    return result


def detect_platform(driver: Any) -> str:
    """Return 'ios' or 'android' from the active session capabilities."""
    capabilities = getattr(driver, "capabilities", None) or {}
    platform = str(capabilities.get("platformName", "")).lower()
    return "ios" if platform == "ios" else "android"


def _element_center(element: Any) -> Tuple[int, int]:
    """Centre point (viewport pixels) of an element via its rect.

    Falls back to location + size for old drivers that lack ``rect``.
    """
    try:
        rect = element.rect
        x = rect.get("x", 0)
        y = rect.get("y", 0)
        width = rect.get("width", 0)
        height = rect.get("height", 0)
        if width and height:
            return int(x + width / 2), int(y + height / 2)
    except Exception:
        pass
    location = element.location  # {"x": ..., "y": ...}
    size = element.size  # {"width": ..., "height": ...}
    return int(location["x"] + size["width"] / 2), int(location["y"] + size["height"] / 2)


def _viewport(driver: Any) -> Tuple[int, int]:
    size = driver.get_window_size()
    return int(size["width"]), int(size["height"])


def _element_rect(element: Any) -> dict:
    try:
        return element.rect
    except (StaleElementReferenceException, WebDriverException):
        raise
    except Exception:
        location = element.location
        size = element.size
        return {"x": location["x"], "y": location["y"], "width": size["width"], "height": size["height"]}


def _point_in_viewport(driver: Any, element: Any, container: Any = None) -> bool:
    """True when the element's frame intersects the container (or viewport)."""
    try:
        rect = _element_rect(element)
    except (StaleElementReferenceException, NoSuchElementException):
        return False
    if not rect.get("width") or not rect.get("height"):
        return False
    if container is not None:
        try:
            c = _element_rect(container)
            cw, ch, cx, cy = c["width"], c["height"], c["x"], c["y"]
        except Exception:
            cw, ch, cx, cy = *_viewport(driver), 0, 0
    else:
        cw, ch = _viewport(driver)
        cx = cy = 0
    overlap_x = min(rect["x"] + rect["width"], cx + cw) - max(rect["x"], cx)
    overlap_y = min(rect["y"] + rect["height"], cy + ch) - max(rect["y"], cy)
    return overlap_x > 0 and overlap_y > 0


# ---------------------------------------------------------------------------
# tap family
# ---------------------------------------------------------------------------
def tap_at(driver: Any, x: float, y: float) -> None:
    """Tap the screen at absolute viewport coordinates (pixels)."""
    pointer = _new_touch("tap")
    pointer.create_pointer_move(duration=0, x=int(x), y=int(y))
    pointer.create_pointer_down(button=0)
    pointer.create_pointer_up(button=0)
    _dispatch(driver, [pointer], "tap", at=(int(x), int(y)))


def tap_element(driver: Any, element: Any) -> None:
    """Tap the centre of an element (W3C, works on both platforms)."""
    x, y = _element_center(element)
    tap_at(driver, x, y)


def _w3c_double_tap(driver: Any, x: int, y: int) -> None:
    pointer = _new_touch("double_tap")
    for _ in range(2):
        pointer.create_pointer_move(duration=0, x=x, y=y)
        pointer.create_pointer_down(button=0)
        pointer.create_pointer_up(button=0)
        pointer.create_pause(_DOUBLE_TAP_PAUSE)
    _dispatch(driver, [pointer], "double_tap", at=(x, y))


def double_tap_at(driver: Any, x: float, y: float) -> None:
    """Double tap at screen coordinates.

    Android: ``mobile: doubleClickGesture`` accepts coordinates.
    iOS: the XCUITest ``mobile: doubleTap`` shortcut only targets elements,
    so coordinate double taps run as two W3C taps 60 ms apart.
    """
    platform = detect_platform(driver)
    if platform == "android":
        try:
            _mobile(
                driver,
                "mobile: doubleClickGesture",
                {"x": int(x), "y": int(y)},
                "double_tap",
                at=(x, y),
            )
            return
        except WebDriverException as exc:
            LOG.warning(
                "Native double tap failed; falling back to W3C double tap",
                kv={"platform": platform, "reason": str(exc)[:200]},
            )
    else:
        LOG.debug("iOS doubleTap shortcut is element-only; using W3C double tap")
    _w3c_double_tap(driver, int(x), int(y))


def double_tap_element(driver: Any, element: Any) -> None:
    """Double tap the centre of an element (native shortcut, W3C fallback).

    Android: ``mobile: doubleClickGesture``; iOS: ``mobile: doubleTap``.
    """
    platform = detect_platform(driver)
    params = {"elementId": element.id}
    try:
        if platform == "android":
            _mobile(driver, "mobile: doubleClickGesture", params, "double_tap_element")
        else:
            _mobile(driver, "mobile: doubleTap", params, "double_tap_element")
    except WebDriverException as exc:
        LOG.warning(
            "Native double tap on element failed; falling back to W3C",
            kv={"platform": platform, "reason": str(exc)[:200]},
        )
        x, y = _element_center(element)
        _w3c_double_tap(driver, x, y)


# ---------------------------------------------------------------------------
# long press
# ---------------------------------------------------------------------------
def _w3c_long_press(driver: Any, x: int, y: int, duration_seconds: float) -> None:
    pointer = _new_touch("long_press")
    pointer.create_pointer_move(duration=0, x=x, y=y)
    pointer.create_pointer_down(button=0)
    pointer.create_pause(duration_seconds)
    pointer.create_pointer_up(button=0)
    _dispatch(driver, [pointer], "long_press", at=(x, y), duration_s=duration_seconds)


def _native_long_press(driver: Any, x: int | None, y: int | None, element: Any | None, duration_seconds: float) -> None:
    platform = detect_platform(driver)
    if platform == "android":
        params = {"duration": int(duration_seconds * 1000)}
        if element is not None:
            params["elementId"] = element.id
        else:
            params.update({"x": int(x), "y": int(y)})
        _mobile(driver, "mobile: longClickGesture", params, "long_press", duration_ms=duration_seconds * 1000)
    else:
        # XCUITest touchAndHold: duration in SECONDS and it is mandatory
        params = {"duration": duration_seconds}
        if element is not None:
            params["elementId"] = element.id
        else:
            params.update({"x": int(x), "y": int(y)})
        _mobile(driver, "mobile: touchAndHold", params, "long_press", duration_s=duration_seconds)


def long_press(
    driver: Any,
    element: Any | None = None,
    x: float | None = None,
    y: float | None = None,
    duration_seconds: float = 1.0,
) -> None:
    """Long-press an element or screen coordinates.

    Android: ``mobile: longClickGesture`` (duration in ms, >= 500 ms is
    registered as a long click). iOS: ``mobile: touchAndHold`` (duration in
    seconds). Falls back to a W3C down-hold-up sequence on failure.
    """
    if element is None and (x is None or y is None):
        raise ValueError("long_press() needs either an element or both x and y.")
    try:
        _native_long_press(driver, x, y, element, duration_seconds)
    except WebDriverException as exc:
        LOG.warning(
            "Native long press failed; falling back to W3C sequence",
            kv={"reason": str(exc)[:200]},
        )
        if element is not None:
            x, y = _element_center(element)
        _w3c_long_press(driver, int(x), int(y), duration_seconds)


def long_press_element(driver: Any, element: Any, duration_seconds: float = 1.0) -> None:
    """Convenience wrapper: long-press the centre of ``element``."""
    long_press(driver, element=element, duration_seconds=duration_seconds)


# ---------------------------------------------------------------------------
# swipe / scroll (W3C, deterministic on both platforms)
# ---------------------------------------------------------------------------
def swipe_between_coordinates(
    driver: Any,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    duration_ms: int = 700,
) -> None:
    """Swipe the finger from (start_x, start_y) to (end_x, end_y).

    ``duration_ms`` controls the speed: ~700-1000 ms feels like a deliberate
    drag-scroll, 100-250 ms like a flick. Coordinates are viewport pixels.
    """
    pointer = _new_touch("swipe")
    pointer.create_pointer_move(duration=0, x=int(start_x), y=int(start_y))
    pointer.create_pointer_down(button=0)
    pointer.create_pointer_move(duration=duration_ms, x=int(end_x), y=int(end_y))
    pointer.create_pause(0.05)  # let the driver register the move end
    pointer.create_pointer_up(button=0)
    _dispatch(
        driver,
        [pointer],
        "swipe_between_coordinates",
        start=(int(start_x), int(start_y)),
        end=(int(end_x), int(end_y)),
        duration_ms=duration_ms,
    )


def swipe_between_elements(
    driver: Any,
    source_element: Any,
    target_element: Any,
    duration_ms: int = 700,
) -> None:
    """Swipe from the centre of one element to the centre of another."""
    sx, sy = _element_center(source_element)
    tx, ty = _element_center(target_element)
    swipe_between_coordinates(driver, sx, sy, tx, ty, duration_ms=duration_ms)


def _region_points(driver: Any, element: Any | None, direction: str, distance_fraction: float) -> tuple:
    """Return (start, end) viewport points for a swipe across an element (or
    the whole screen). Direction = finger travel; coordinates are clamped to
    the region so large fractions never send the finger off-screen."""
    if element is not None:
        rect = _element_rect(element)
        left, top = int(rect["x"]), int(rect["y"])
        width, height = int(rect["width"]), int(rect["height"])
    else:
        left, top = 0, 0
        width, height = _viewport(driver)

    if width <= 0 or height <= 0:
        width, height = _viewport(driver)
        left = top = 0

    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(value, high))

    x_lo, x_hi = left, left + max(width - 1, 0)
    y_lo, y_hi = top, top + max(height - 1, 0)
    cx = _clamp(left + width // 2, x_lo, x_hi)
    cy = _clamp(top + height // 2, y_lo, y_hi)
    d = max(0.0, min(distance_fraction, 1.0))  # fraction of the region travelled

    if direction == "up":
        return (cx, _clamp(top + int(height * 0.85), y_lo, y_hi)), (
            cx,
            _clamp(top + int(height * (0.85 - d)), y_lo, y_hi),
        )
    if direction == "down":
        return (cx, _clamp(top + int(height * 0.15), y_lo, y_hi)), (
            cx,
            _clamp(top + int(height * (0.15 + d)), y_lo, y_hi),
        )
    if direction == "left":
        return (_clamp(left + int(width * 0.85), x_lo, x_hi), cy), (
            _clamp(left + int(width * (0.85 - d)), x_lo, x_hi),
            cy,
        )
    if direction == "right":
        return (_clamp(left + int(width * 0.15), x_lo, x_hi), cy), (
            _clamp(left + int(width * (0.15 + d)), x_lo, x_hi),
            cy,
        )
    raise ValueError(f"direction must be up/down/left/right, got {direction!r}")


def _swipe_direction(
    driver: Any,
    direction: str,
    element: Any | None = None,
    distance_fraction: float = 0.75,
    duration_ms: int = 700,
    gesture_name: str = "swipe",
) -> None:
    (sx, sy), (ex, ey) = _region_points(driver, element, direction, distance_fraction)
    swipe_between_coordinates(driver, sx, sy, ex, ey, duration_ms=duration_ms)
    LOG.info("Directional swipe", kv={"gesture": gesture_name, "direction": direction, "element": element is not None})


def swipe_up(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Finger travels upward; content further down the page is revealed."""
    _swipe_direction(driver, "up", element, distance_fraction, duration_ms, "swipe_up")


def swipe_down(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Finger travels downward; content further up the page is revealed."""
    _swipe_direction(driver, "down", element, distance_fraction, duration_ms, "swipe_down")


def swipe_left(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Finger travels left; content to the right is revealed."""
    _swipe_direction(driver, "left", element, distance_fraction, duration_ms, "swipe_left")


def swipe_right(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Finger travels right; content to the left is revealed."""
    _swipe_direction(driver, "right", element, distance_fraction, duration_ms, "swipe_right")


# scroll_* are semantic aliases of the swipe_* family
def scroll_up(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Scroll the page downwards (finger travels up)."""
    swipe_up(driver, element, distance_fraction, duration_ms)


def scroll_down(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    """Scroll the page upwards (finger travels down)."""
    swipe_down(driver, element, distance_fraction, duration_ms)


def scroll_left(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    swipe_left(driver, element, distance_fraction, duration_ms)


def scroll_right(driver: Any, element: Any | None = None, distance_fraction: float = 0.75, duration_ms: int = 700) -> None:
    swipe_right(driver, element, distance_fraction, duration_ms)


# ---------------------------------------------------------------------------
# flick / fling
# ---------------------------------------------------------------------------
def flick_between_coordinates(
    driver: Any,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    duration_ms: int = 120,
) -> None:
    """Fast short swipe = flick (W3C; both platforms).

    iOS note: there is no XCUITest native flick command; a quick W3C swipe
    is the recommended equivalent.
    """
    swipe_between_coordinates(driver, start_x, start_y, end_x, end_y, duration_ms=duration_ms)


def flick_up(driver: Any, element: Any | None = None, distance_fraction: float = 0.5, duration_ms: int = 120) -> None:
    """Quick flick upward (reveals content below the fold)."""
    _swipe_direction(driver, "up", element, distance_fraction, duration_ms, "flick_up")


def flick_down(driver: Any, element: Any | None = None, distance_fraction: float = 0.5, duration_ms: int = 120) -> None:
    _swipe_direction(driver, "down", element, distance_fraction, duration_ms, "flick_down")


def flick_left(driver: Any, element: Any | None = None, distance_fraction: float = 0.5, duration_ms: int = 120) -> None:
    _swipe_direction(driver, "left", element, distance_fraction, duration_ms, "flick_left")


def flick_right(driver: Any, element: Any | None = None, distance_fraction: float = 0.5, duration_ms: int = 120) -> None:
    _swipe_direction(driver, "right", element, distance_fraction, duration_ms, "flick_right")


def fling_android(driver: Any, direction: str, speed: int | None = None) -> None:
    """Native Android velocity fling (``mobile: flingGesture``).

    Only available on Android. Use ``flick_*`` on iOS instead.
    """
    platform = detect_platform(driver)
    if platform != "android":
        raise GestureNotSupportedError(
            "fling_android() requires the UiAutomator2 driver (Android). "
            "On iOS use flick_up()/flick_down()/... instead."
        )
    params: dict = {"direction": direction}
    if speed is not None:
        params["speed"] = int(speed)
    _mobile(driver, "mobile: flingGesture", params, "fling_android", direction=direction)


# ---------------------------------------------------------------------------
# scroll to element
# ---------------------------------------------------------------------------
def _locator_of(by: Any, value: Any) -> tuple:
    if value is None and isinstance(by, (tuple, list)) and len(by) == 2:
        return tuple(by)
    return (by, value)


def scroll_to_element(
    driver: Any,
    by: Any,
    value: Any = None,
    direction: str = "up",
    max_swipes: int = 10,
    container: Any | None = None,
    distance_fraction: float = 0.7,
) -> WebElement:
    """Swipe repeatedly until the target element scrolls into the viewport.

    Args:
        by/value: locator (or a ready-made ``(by, value)`` tuple as ``by``).
        direction: finger travel direction used to look for the element.
                   'up' reveals content below (the common case).
        max_swipes: safety valve before :class:`ElementNotFoundError`.
        container: optional scrollable container element to scroll inside and
                   to use as the visibility reference.
        distance_fraction: how far each swipe travels.

    Returns the visible element. Raises :class:`ElementNotFoundError` when
    the element did not appear after ``max_swipes`` attempts.
    """
    locator = _locator_of(by, value)
    LOG.info("Scrolling to element", kv={"locator": (locator[0], locator[1]), "direction": direction, "max_swipes": max_swipes})
    last_error: Exception | None = None

    for attempt in range(1, max_swipes + 1):
        try:
            element = driver.find_element(*locator)
            if _point_in_viewport(driver, element, container):
                LOG.info("Element found in viewport", kv={"attempt": attempt, "locator": (locator[0], locator[1])})
                return element
            LOG.debug("Element exists but is outside the viewport", kv={"attempt": attempt})
        except NoSuchElementException:
            LOG.debug("Element not found yet", kv={"attempt": attempt})
        except StaleElementReferenceException as exc:
            last_error = exc
        _swipe_direction(driver, direction, element=container, distance_fraction=distance_fraction, duration_ms=500, gesture_name="scroll_to_element")

    detail = f" (last error: {last_error})" if last_error else ""
    raise ElementNotFoundError(
        f"Element ({locator[0]}, {locator[1]!r}) not visible after {max_swipes} swipes in direction {direction!r}.{detail} "
        f"Check the locator, the swipe direction, or increase max_swipes."
    )


# ---------------------------------------------------------------------------
# drag and drop
# ---------------------------------------------------------------------------
def drag_and_drop(
    driver: Any,
    source_element: Any,
    target_element: Any,
    hold_seconds: float = 1.0,
    move_duration_ms: int = 800,
) -> None:
    """Drag an element onto another element.

    W3C sequence: press the source centre, hold it for ``hold_seconds``
    (Android registers a long-click-drag after ~0.5 s), glide to the target
    centre over ``move_duration_ms`` and release.

    iOS alternative (kept for reference, not used by default):
    ``mobile: dragFromToForDuration`` requires coordinates in *points* plus a
    duration in seconds - W3C actions accept the same geometry with pixels.
    """
    sx, sy = _element_center(source_element)
    tx, ty = _element_center(target_element)
    pointer = _new_touch("drag")
    pointer.create_pointer_move(duration=0, x=sx, y=sy)
    pointer.create_pointer_down(button=0)
    pointer.create_pause(hold_seconds)
    pointer.create_pointer_move(duration=move_duration_ms, x=tx, y=ty)
    pointer.create_pause(0.05)
    pointer.create_pointer_up(button=0)
    _dispatch(
        driver,
        [pointer],
        "drag_and_drop",
        source=(sx, sy),
        target=(tx, ty),
        hold_s=hold_seconds,
        move_ms=move_duration_ms,
    )


# ---------------------------------------------------------------------------
# pinch / zoom (native where possible)
# ---------------------------------------------------------------------------
def _w3c_pinch(driver: Any, x: int, y: int, zoom_in: bool, spread: int = 120, duration_ms: int = 400) -> None:
    """Generic two-finger pinch with W3C actions (fallback engine)."""
    finger_a = _new_touch("pinch_a")
    finger_b = _new_touch("pinch_b")
    if zoom_in:  # fingers start close together and spread apart
        a_start, b_start, a_end, b_end = (x - 15, y), (x + 15, y), (x - spread, y), (x + spread, y)
    else:  # fingers start apart and come together
        a_start, b_start, a_end, b_end = (x - spread, y), (x + spread, y), (x - 15, y), (x + 15, y)
    for pointer, (sx, sy), (ex, ey) in ((finger_a, a_start, a_end), (finger_b, b_start, b_end)):
        pointer.create_pointer_move(duration=0, x=sx, y=sy)
        pointer.create_pointer_down(button=0)
        pointer.create_pointer_move(duration=duration_ms, x=ex, y=ey)
        pointer.create_pause(0.05)
        pointer.create_pointer_up(button=0)
    _dispatch(driver, [finger_a, finger_b], "pinch_open" if zoom_in else "pinch_close", centre=(x, y))


def zoom_in(driver: Any, element: Any | None = None) -> None:
    """Pinch OUT (spread fingers) = zoom in.

    Android: ``mobile: pinchOpenGesture`` (percent of the area/element).
    iOS: ``mobile: pinch`` with scale > 1 (XCUITest ``pinchWithScale``).
    """
    platform = detect_platform(driver)
    try:
        if platform == "android":
            params: dict = {"percent": 0.5}
            if element is not None:
                params["elementId"] = element.id
            _mobile(driver, "mobile: pinchOpenGesture", params, "zoom_in")
        else:
            params = {"scale": 1.5, "velocity": 1.0}
            if element is not None:
                params["elementId"] = element.id
            _mobile(driver, "mobile: pinch", params, "zoom_in", scale=1.5)
    except WebDriverException as exc:
        LOG.warning("Native pinch open failed; using W3C fallback", kv={"reason": str(exc)[:200]})
        x, y = _element_center(element) if element is not None else (_viewport(driver)[0] // 2, _viewport(driver)[1] // 2)
        _w3c_pinch(driver, x, y, zoom_in=True)


def zoom_out(driver: Any, element: Any | None = None) -> None:
    """Pinch IN (bring fingers together) = zoom out.

    Android: ``mobile: pinchCloseGesture``; iOS: ``mobile: pinch`` with
    scale < 1.
    """
    platform = detect_platform(driver)
    try:
        if platform == "android":
            params: dict = {"percent": 0.5}
            if element is not None:
                params["elementId"] = element.id
            _mobile(driver, "mobile: pinchCloseGesture", params, "zoom_out")
        else:
            params = {"scale": 0.5, "velocity": 1.0}
            if element is not None:
                params["elementId"] = element.id
            _mobile(driver, "mobile: pinch", params, "zoom_out", scale=0.5)
    except WebDriverException as exc:
        LOG.warning("Native pinch close failed; using W3C fallback", kv={"reason": str(exc)[:200]})
        x, y = _element_center(element) if element is not None else (_viewport(driver)[0] // 2, _viewport(driver)[1] // 2)
        _w3c_pinch(driver, x, y, zoom_in=False)


# ---------------------------------------------------------------------------
# platform-level commands
# ---------------------------------------------------------------------------
def back(driver: Any) -> None:
    """Press the Android system back button.

    iOS has no system back; use the application's own navigation controls
    via page objects (e.g. ``nav_bar.tap_back()``).
    """
    if detect_platform(driver) == "android":
        driver.back()
        LOG.info("Gesture performed", kv={"gesture": "back_android"})
        return
    raise GestureNotSupportedError(
        "back() is only available on Android. iOS applications expose their "
        "own back/navigation buttons - interact with those through page objects."
    )


def is_keyboard_shown(driver: Any) -> bool:
    """True when the soft keyboard is currently on screen (both platforms)."""
    try:
        return bool(driver.is_keyboard_shown())
    except WebDriverException as exc:
        LOG.debug("Keyboard state unknown", kv={"reason": str(exc)[:120]})
        return False


def hide_keyboard(driver: Any, strategy: str | None = None) -> None:
    """Hide the soft keyboard if it is visible.

    Android: sends the KEYCODE_BACK key event (only when the keyboard is
    actually shown - never backgrounds the app). iOS: taps the keyboard
    dismiss key (default strategy; pass ``strategy="pressKey"`` or
    ``"swipeDown"`` for the XCUITest alternatives).

    Never raises when the keyboard is already hidden - logs instead.
    """
    platform = detect_platform(driver)
    if platform == "android" and not is_keyboard_shown(driver):
        LOG.debug("Keyboard not shown; nothing to hide")
        return
    try:
        if platform == "android":
            driver.hide_keyboard(strategy=strategy or "keycode")
        else:
            driver.hide_keyboard(strategy=strategy or "default")
        LOG.info("Gesture performed", kv={"gesture": "hide_keyboard", "platform": platform, "strategy": strategy or "default"})
    except WebDriverException as exc:
        LOG.warning("Failed to hide keyboard (it may already be hidden)", kv={"reason": str(exc)[:200]})


# Backwards-friendly aliases --------------------------------------------------
def tap(driver: Any, x: float, y: float) -> None:
    """Alias for :func:`tap_at`."""
    tap_at(driver, x, y)


def double_tap(driver: Any, x: float | None = None, y: float | None = None, element: Any | None = None) -> None:
    """Double tap at coordinates or on an element (see module docstring)."""
    if element is not None:
        double_tap_element(driver, element)
    elif x is not None and y is not None:
        double_tap_at(driver, x, y)
    else:
        raise ValueError("double_tap() needs an element or both x and y.")


def scroll(
    driver: Any,
    direction: str,
    element: Any | None = None,
    distance_fraction: float = 0.75,
    duration_ms: int = 700,
) -> None:
    """Generic scroll in ``up|down|left|right`` (finger travel semantics)."""
    _swipe_direction(driver, direction, element, distance_fraction, duration_ms, "scroll")


def flick(
    driver: Any,
    direction: str,
    element: Any | None = None,
    distance_fraction: float = 0.5,
    duration_ms: int = 120,
) -> None:
    """Generic flick in ``up|down|left|right`` (finger travel semantics)."""
    _swipe_direction(driver, direction, element, distance_fraction, duration_ms, "flick")

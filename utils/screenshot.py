"""Failure-artifact capture: screenshots and page source.

Every test failure triggers ``capture_failure_artifacts`` (see
``conftest.py``); pages can also take deliberate screenshots with
``save_screenshot`` (e.g. at the end of a smoke test).

Where are the artifacts stored?
-------------------------------
* ``artifacts/screenshots/``  -> PNG screenshots, named ``<test>_<timestamp>.png``
* ``artifacts/page_source/``  -> XML snapshots of the view hierarchy at the
  moment of failure (invaluable for debugging locator problems)

Both locations come from ``paths`` in ``config/settings.yaml`` and are
created on demand.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

LOG = get_logger("utils.screenshot")

_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S_%f"


def _timestamp() -> str:
    return datetime.now().strftime(_TIMESTAMP_FORMAT)


def _safe_name(name: str) -> str:
    """Keep artifact filenames filesystem- and shell-friendly."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)


def _prepare_dir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_screenshot(driver, directory: Path, name: str) -> Path:
    """Save ``driver``'s current screen as a PNG. Returns the file path."""
    directory = _prepare_dir(Path(directory))
    target = directory / f"{_safe_name(name)}_{_timestamp()}.png"
    try:
        png = driver.get_screenshot_as_png()
    except Exception as exc:  # driver may already be gone (e.g. session crash)
        LOG.warning("Could not take screenshot", kv={"reason": str(exc), "target": str(target)})
        raise
    target.write_bytes(png)
    LOG.info("Screenshot saved", kv={"path": str(target)})
    return target


def save_page_source(driver, directory: Path, name: str) -> Path:
    """Save the current XML view hierarchy. Returns the file path."""
    directory = _prepare_dir(Path(directory))
    target = directory / f"{_safe_name(name)}_{_timestamp()}.xml"
    try:
        source = driver.page_source
    except Exception as exc:
        LOG.warning("Could not capture page source", kv={"reason": str(exc)})
        raise
    target.write_text(source or "", encoding="utf-8")
    LOG.info("Page source saved", kv={"path": str(target)})
    return target


def capture_failure_artifacts(
    driver,
    name: str,
    screenshot_dir: Path,
    page_source_dir: Path,
) -> dict:
    """Best-effort capture of screenshot + page source after a failure.

    Never raises: artifact capture must not mask the original test error.
    Returns a dict of what was captured (used by pytest hooks for logging).
    """
    captured = {}
    if driver is None:
        return captured
    # A driver whose session already ended cannot produce artifacts
    try:
        if not getattr(driver, "session_id", None):
            return captured
    except Exception:
        return captured

    for kind, saver, directory in (
        ("screenshot", save_screenshot, screenshot_dir),
        ("page_source", save_page_source, page_source_dir),
    ):
        try:
            captured[kind] = saver(driver, directory, name)
        except Exception as exc:
            LOG.error(f"Failed to capture {kind}", kv={"reason": str(exc)})
    return captured

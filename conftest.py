"""pytest bootstrap for the mobile framework.

What happens here, in order
---------------------------
1. ``pytest_addoption``        -> the CLI contract (--platform, --device-name,
   --udid) so suites run with ``pytest --platform ios`` etc.
2. ``pytest_configure``        -> resolves the final platform (CLI > env >
   settings default), loads Settings, prepares log/artifact directories and
   installs the logging configuration.
3. ``appium_server`` fixture   -> session-scoped Appium lifecycle. Started
   only when needed; stopped only if this run started it.
4. ``driver`` fixture          -> session-scoped driver via DriverFactory;
   cleaned up reliably afterwards.
5. pytest hooks                -> test start/end logging and automatic
   screenshot + page-source capture on failure.

Platform selection precedence:  ``--platform ios`` > ``APP_PLATFORM=ios``
environment variable > ``android`` default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # framework root importable from anywhere

import pytest

from drivers.driver_factory import DriverFactory
from utils.appium_server import AppiumServer
from utils.config_reader import Settings, load_settings, resolve_platform
from utils.logger import get_logger, setup_logging
from utils.screenshot import capture_failure_artifacts

LOG = get_logger("conftest")


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("appium framework")
    group.addoption(
        "--platform",
        action="store",
        choices=["android", "ios"],
        default=None,
        help="Target platform: android or ios (default: APP_PLATFORM env or android)",
    )
    group.addoption(
        "--device-name",
        action="store",
        default=None,
        help="Override the device/simulator name from config/<platform>.yaml",
    )
    group.addoption(
        "--udid",
        action="store",
        default=None,
        help="Override the device UDID from config/<platform>.yaml",
    )


# ---------------------------------------------------------------------------
# configuration phase
# ---------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    # 1) Resolve the platform (CLI > APP_PLATFORM > android) and expose it
    #    through the environment so test modules can read it at import time.
    platform = resolve_platform(config.getoption("platform"))
    os.environ["APP_PLATFORM"] = platform

    # 2) CLI device overrides are injected as env vars (highest precedence,
    #    single code path in config_reader).
    if config.getoption("device_name"):
        os.environ["APP_DEVICE_NAME"] = str(config.getoption("device_name"))
    if config.getoption("udid"):
        os.environ["APP_UDID"] = str(config.getoption("udid"))

    # 3) Load settings + prepare runtime directories + logging
    settings = load_settings(platform)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings.page_source_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(settings.log_dir, level=settings.log_level, console=True)
    config._appium_settings = settings  # type: ignore[attr-defined]

    LOG.info("=" * 78)
    LOG.info("pytest configured for mobile test run")
    LOG.info("Platform", kv={"platform": platform})
    LOG.info("Target", kv={"summary": settings.summary()})
    LOG.info(
        "Paths",
        kv={
            "logs": str(settings.log_dir),
            "screenshots": str(settings.screenshot_dir),
            "page_source": str(settings.page_source_dir),
        },
    )
    LOG.info("Appium server", kv={"url": settings.server_url(), "external": settings.external})
    LOG.info("=" * 78)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    settings: Settings = getattr(session.config, "_appium_settings", None)  # type: ignore[attr-defined]
    if settings is None:
        return
    reporter = getattr(session.config, "_terminalreporter", None)
    counts = {}
    if reporter is not None:
        stats = reporter.stats or {}
        for outcome in ("passed", "failed", "skipped", "error"):
            counts[outcome] = len(stats.get(outcome, []))
    LOG.info(
        "Test session finished",
        kv={"exitstatus": exitstatus, **counts, "suite_log": str(settings.log_dir / "suite.log")},
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def settings(request: pytest.FixtureRequest) -> Settings:
    """Resolved runtime settings (platform, device, paths, timeouts...)."""
    return request.config._appium_settings  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def appium_server(request: pytest.FixtureRequest) -> AppiumServer:
    """Ensure an Appium server is running for the whole session.

    * external mode: verifies the external server answers, never manages it;
    * auto mode: starts a local server only if none is running; stops it at
      session end only if this run started it (reused servers stay up).
    """
    settings: Settings = request.config._appium_settings  # type: ignore[attr-defined]
    LOG.info("Appium server fixture: ensuring a server is available")
    server = AppiumServer(settings)
    try:
        server.start()
    except Exception:
        LOG.exception("Appium server could not be made available - aborting session")
        raise
    yield server
    server.stop()


@pytest.fixture(scope="session")
def driver(appium_server: AppiumServer, request: pytest.FixtureRequest):
    """Session-scoped Appium driver for the configured platform."""
    settings: Settings = request.config._appium_settings  # type: ignore[attr-defined]
    factory = DriverFactory(settings)
    created = factory.create_driver()
    yield created
    factory.quit_driver(created)


# ---------------------------------------------------------------------------
# hooks: test logging + failure artifacts
# ---------------------------------------------------------------------------
def pytest_runtest_setup(item: pytest.Item) -> None:
    LOG.info(
        "TEST START",
        kv={
            "test": item.name,
            "module": item.module.__name__ if item.module else "?",
            "platform": os.environ.get("APP_PLATFORM", "?"),
        },
    )


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    if call.when != "call":
        return
    duration = round(call.duration, 2) if hasattr(call, "duration") else "?"
    outcome = "passed" if call.excinfo is None else "failed"
    LOG.info("TEST FINISH", kv={"test": item.name, "outcome": outcome, "duration_s": duration})
    if call.excinfo is not None:
        _capture_failure_artifacts(item)


def _capture_failure_artifacts(item: pytest.Item) -> None:
    """Screenshot + page source after a failure (best effort, never raises)."""
    try:
        driver = item.funcargs.get("driver")
    except Exception:
        driver = None
    if driver is None:
        LOG.debug("No driver available; skipping failure artifacts")
        return
    settings: Settings = item.config._appium_settings  # type: ignore[attr-defined]
    name = f"{item.name}_{os.environ.get('APP_PLATFORM', 'unknown')}"
    captured = capture_failure_artifacts(
        driver,
        name,
        screenshot_dir=settings.screenshot_dir,
        page_source_dir=settings.page_source_dir,
    )
    LOG.error("Test failed - failure artifacts saved", kv=captured)

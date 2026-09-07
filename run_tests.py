#!/usr/bin/env python3
"""run_tests.py - one-command test runner for the mobile framework.

Usage
-----
    python run_tests.py                          # android, auto Appium server
    python run_tests.py --platform ios           # iOS
    python run_tests.py --external-server        # attach to a running server
    python run_tests.py --platform android -k login -x   # pytest args pass through

Everything after the runner's own options is forwarded to pytest, so the
full pytest CLI (``-k``, ``-m``, ``-x``, ``--html=report.html`` ...) keeps
working. The equivalent pure-pytest invocation is:

    APP_PLATFORM=ios pytest tests/
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from utils.config_reader import load_settings  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

LOG = get_logger("run_tests")

RUNNER_OPTIONS = ("--platform", "--external-server", "--device-name", "--udid")


def _parse_runner_args(argv: list[str]):
    """Split argv into (runner options, pytest args). pytest args pass through."""
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--platform", choices=["android", "ios"], default=None)
    parser.add_argument("--external-server", action="store_true", help="Attach to an externally managed Appium server")
    parser.add_argument("--device-name", default=None)
    parser.add_argument("--udid", default=None)
    namespace, rest = parser.parse_known_args(argv)
    return namespace, rest


def _banner(platform: str) -> None:
    """Resolve settings and print a short, useful summary before running."""
    settings = load_settings(platform)
    setup_logging(settings.log_dir, level=settings.log_level, console=True)
    LOG.info("=" * 78)
    LOG.info("Mobile test run")
    LOG.info("Target", kv={"summary": settings.summary()})
    LOG.info("Appium server", kv={"url": settings.server_url(), "external": settings.external})
    LOG.info(
        "Artifacts",
        kv={
            "suite_log": str(settings.log_dir / "suite.log"),
            "screenshots": str(settings.screenshot_dir),
        },
    )
    LOG.info("=" * 78)
    print(f"\nRunning {platform} tests with pytest...\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    namespace, pytest_args = _parse_runner_args(argv)

    # Runner options become environment variables (highest precedence) so the
    # pytest run and the banner agree on every value.
    platform = namespace.platform or os.environ.get("APP_PLATFORM", "android")
    os.environ["APP_PLATFORM"] = platform
    if namespace.external_server:
        os.environ["APP_EXTERNAL"] = "true"
    if namespace.device_name:
        os.environ["APP_DEVICE_NAME"] = namespace.device_name
    if namespace.udid:
        os.environ["APP_UDID"] = namespace.udid

    _banner(platform)

    command = [sys.executable, "-m", "pytest", str(ROOT / "tests"), *pytest_args]
    LOG.info("Executing", kv={"command": " ".join(command)})
    try:
        result = subprocess.run(command, cwd=str(ROOT))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    return int(result.returncode)


if __name__ == "__main__":
    sys.exit(main())

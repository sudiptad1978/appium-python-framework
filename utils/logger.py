"""Structured logging for the framework.

Design notes
------------
* A single parent logger (``appium_framework``) owns two handlers:
  a rotating file handler (``logs/suite.log``) and, optionally, a colored
  console handler. Component loggers are children of it, so *one* call to
  ``setup_logging()`` configures the whole suite - including the Appium
  server manager and pytest hooks.
* ``get_logger(name)`` returns a tiny wrapper whose methods accept
  ``kv=...`` keyword arguments for structured key=value context, e.g.::

      log = get_logger(__name__)
      log.info('Driver created', kv={'session_id': sid, 'platform': 'android'})

* Timestamps are local time in ISO-8601 form, which sorts cleanly when logs
  are diffed across machines/timezones.

Where are the logs?
-------------------
* ``logs/suite.log``          -> everything the framework + tests log
* ``logs/appium_server.log``  -> stdout of the spawned Appium server process
  (see ``utils/appium_server.py``)
Both directories are created automatically and are git-ignored.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PARENT_NAME = "appium_framework"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# ANSI colours for terminals that support them
_COLORS = {
    "DEBUG": "\033[2m",       # faint
    "INFO": "\033[0m",
    "WARNING": "\033[33m",    # yellow
    "ERROR": "\033[31m",      # red
    "CRITICAL": "\033[41m",   # red background
}
_RESET = "\033[0m"


class _ColoredFormatter(logging.Formatter):
    """Adds ANSI colours to the console handler when stdout is a TTY."""

    def __init__(self, fmt: str, use_color: bool):
        super().__init__(fmt=fmt, datefmt=_TIMESTAMP_FORMAT)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self._use_color:
            return message
        color = _COLORS.get(record.levelname, _RESET)
        return f"{color}{message}{_RESET}"


class _Logger:
    """Thin wrapper adding structured ``kv=...`` context to a child logger."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(f"{PARENT_NAME}.{name}")
        self._name = name

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _with_kv(message: str, kv: dict | None) -> str:
        if not kv:
            return message
        context = " ".join(f"{key}={value}" for key, value in kv.items())
        return f"{message} | {context}"

    # -- logging methods --------------------------------------------------
    def debug(self, message: str, *args, kv: dict | None = None, **kwargs) -> None:
        self._logger.debug(self._with_kv(message, kv), *args, **kwargs)

    def info(self, message: str, *args, kv: dict | None = None, **kwargs) -> None:
        self._logger.info(self._with_kv(message, kv), *args, **kwargs)

    def warning(self, message: str, *args, kv: dict | None = None, **kwargs) -> None:
        self._logger.warning(self._with_kv(message, kv), *args, **kwargs)

    def error(self, message: str, *args, kv: dict | None = None, **kwargs) -> None:
        self._logger.error(self._with_kv(message, kv), *args, **kwargs)

    def exception(self, message: str, *args, kv: dict | None = None, **kwargs) -> None:
        """Logs at ERROR level including the current exception traceback."""
        self._logger.exception(self._with_kv(message, kv), *args, **kwargs)


def setup_logging(log_dir: Path, level: str = "INFO", console: bool = True) -> logging.Logger:
    """Configure the parent logger once (idempotent).

    Args:
        log_dir: Directory for ``suite.log``; created if missing.
        level:   Minimum level ("DEBUG" | "INFO" | "WARNING" | "ERROR").
        console: Mirror log records to stdout (colored on TTYs).

    Returns:
        The parent ``logging.Logger``.
    """
    parent = logging.getLogger(PARENT_NAME)
    if getattr(parent, "_fw_configured", False):
        return parent

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    parent.setLevel(logging.DEBUG)  # children decide via handler level
    level_upper = str(level).strip().upper()

    # File handler: everything >= configured level, plain text
    file_handler = logging.FileHandler(log_dir / "suite.log", encoding="utf-8")
    file_handler.setLevel(level_upper)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_TIMESTAMP_FORMAT))
    parent.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level_upper)
        use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        console_handler.setFormatter(_ColoredFormatter(_LOG_FORMAT, use_color=use_color))
        parent.addHandler(console_handler)

    parent._fw_configured = True  # type: ignore[attr-defined]
    return parent


def get_logger(name: str) -> _Logger:
    """Return a structured logger child: ``get_logger(__name__)``."""
    return _Logger(name)

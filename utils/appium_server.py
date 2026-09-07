"""Appium 2.x server lifecycle management.

Responsibilities
----------------
* start an Appium server automatically (``AppiumServer.start()``) when none
  is answering on the configured host:port - and only then;
* reuse an already-running server (health check via the W3C ``/status``
  endpoint before spawning anything);
* stop the server at the end of the run - but **only** if this process
  started it. Externally managed servers (CI services, Appium Desktop,
  docker/grid) are never touched when ``settings.external`` is true;
* redirect the server's stdout into ``logs/appium_server.log`` and surface
  ERROR/WARN lines in the suite logger;
* fail with actionable messages (log excerpts included) when anything goes
  wrong.

Compatibility: macOS/Linux + Windows (``appium.cmd`` on Windows). The
Appium executable is located via the configured path or ``$PATH``.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from utils.config_reader import Settings
from utils.errors import AppiumServerError
from utils.logger import get_logger

LOG = get_logger("appium_server")

_POLL_INTERVAL = 0.5  # seconds between health checks while waiting


# ---------------------------------------------------------------------------
# module-level network helpers (reused by the driver factory too)
# ---------------------------------------------------------------------------
def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Cheap TCP probe - answers the question "is something listening?"."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_status(health_url: str, timeout: float = 3.0) -> Optional[dict]:
    """GET the W3C /status endpoint; return the parsed JSON (or None).

    A reachable endpoint is the definitive "an Appium server is running"
    signal (a plain TCP listener is not enough - it could be any process).
    """
    try:
        response = requests.get(health_url, timeout=timeout)
        if response.status_code != 200:
            return None
        payload = response.json()
        if isinstance(payload, dict) and "value" in payload and isinstance(payload["value"], dict):
            return payload["value"]
        return payload if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError):
        return None


def _server_version(status: dict) -> str:
    build = status.get("build") or {}
    return str(build.get("version", "unknown"))


# ---------------------------------------------------------------------------
# server manager
# ---------------------------------------------------------------------------
class AppiumServer:
    """Manages the local Appium server process for one test run."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._process: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None
        self._log_file: Optional[Path] = None
        self._started_by_us = False

    # -- public API ----------------------------------------------------- #
    @property
    def started_by_us(self) -> bool:
        return self._started_by_us

    def is_running(self) -> bool:
        """True when an Appium server answers on the configured endpoint."""
        return fetch_status(self._settings.health_url(), timeout=1.5) is not None

    def start(self) -> bool:
        """Ensure an Appium server is running; returns True if this call
        started it (and therefore owns its shutdown)."""
        settings = self._settings
        if settings.external:
            return self._attach_external()
        if self.is_running():
            status = fetch_status(settings.health_url())
            version = _server_version(status) if status else "unknown"
            LOG.info(
                "Appium server already running - reusing it (no second instance started)",
                kv={"url": settings.server_url(), "version": version},
            )
            return False
        if not settings.auto_start:
            raise AppiumServerError(
                f"No Appium server reachable at {settings.server_url()} and "
                f"auto_start is disabled. Start a server yourself "
                f"('appium server --address {settings.host} --port {settings.port}') "
                f"or enable auto_start/external in config/settings.yaml."
            )
        return self._launch()

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Block until /status answers (for externally managed servers)."""
        deadline = time.monotonic() + (timeout or self._settings.start_timeout_seconds)
        while time.monotonic() < deadline:
            status = fetch_status(self._settings.health_url())
            if status is not None:
                LOG.info("Appium server is ready", kv={"version": _server_version(status)})
                return True
            time.sleep(_POLL_INTERVAL)
        return False

    def stop(self) -> bool:
        """Stop the server - but only if this run started it.

        Returns True when a process was terminated by this call.
        """
        settings = self._settings
        if settings.external:
            LOG.info("Externally managed server - not stopping it")
            return False
        if self._process is None:
            LOG.info("No Appium server was started by this run - nothing to stop")
            return False

        process = self._process
        try:
            exit_code = process.poll()
        except Exception:
            exit_code = None
        if exit_code is not None:
            LOG.warning("Appium server process already exited", kv={"exit_code": exit_code})
            self._process = None
            self._started_by_us = False
            return False

        LOG.info("Stopping Appium server", kv={"pid": process.pid})
        try:
            process.terminate()  # SIGTERM (POSIX) / TerminateProcess (Windows)
        except OSError as exc:
            LOG.warning("Could not send terminate signal", kv={"reason": str(exc)})
        try:
            process.communicate(timeout=self._settings.stop_timeout_seconds)
        except subprocess.TimeoutExpired:
            LOG.warning("Graceful stop timed out - killing the server process")
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        self._process = None
        self._started_by_us = False
        LOG.info("Appium server stopped")
        return True

    def __enter__(self) -> "AppiumServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()

    # -- internals ------------------------------------------------------ #
    def _attach_external(self) -> bool:
        """Validate connectivity to an externally managed server."""
        settings = self._settings
        LOG.info(
            "External Appium server mode",
            kv={"url": settings.server_url(), "timeout_s": settings.start_timeout_seconds},
        )
        if self.wait_until_ready():
            LOG.info("Connected to externally managed Appium server")
            return False
        raise AppiumServerError(
            f"External Appium server not reachable at {settings.server_url()} "
            f"after {settings.start_timeout_seconds}s. Start it first, e.g.:\n"
            f"  appium server --address {settings.host} --port {settings.port}\n"
            f"or point the framework at the right host/port in config/settings.yaml."
        )

    def _resolve_binary(self) -> str:
        configured = self._settings.binary.strip()
        if configured:
            if Path(configured).exists():
                return configured
            found = shutil.which(configured)
            if found:
                return found
            raise AppiumServerError(
                f"Configured APPIUM_BINARY {configured!r} does not exist. "
                f"Fix settings.yaml / the APPIUM_BINARY environment variable."
            )
        found = shutil.which("appium")
        if not found and sys.platform == "win32":
            found = shutil.which("appium.cmd")  # npm .cmd shim on Windows
        if not found:
            raise AppiumServerError(
                "The 'appium' executable was not found on $PATH. Install it with:\n"
                "  npm install -g appium@2\n"
                "  appium driver install uiautomator2    # Android\n"
                "  appium driver install xcuitest        # iOS\n"
                "or set APPIUM_BINARY to the absolute path of the executable."
            )
        return found

    def _launch(self) -> bool:
        settings = self._settings
        binary = self._resolve_binary()

        command = [
            binary,
            "server",
            "--address", settings.host,
            "--port", str(settings.port),
            "--log-level", settings.server_log_level,
            "--log-no-colors",
            "--log-timestamp",
        ]
        if settings.base_path.strip():
            command += ["--base-path", settings.base_path.strip("/") or "/"]
        if settings.use_drivers:
            command += ["--use-drivers", ",".join(settings.use_drivers)]

        log_dir = settings.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = log_dir / "appium_server.log"

        LOG.info(
            "Starting Appium server",
            kv={"command": " ".join(command), "log_file": str(self._log_file)},
        )

        # Detach the child from our process group so cleanup works cleanly
        # on both POSIX and Windows.
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
            )
        except OSError as exc:
            raise AppiumServerError(f"Failed to launch Appium server: {exc}") from exc

        self._log_thread = threading.Thread(
            target=self._consume_stdout,
            name="appium-server-log",
            daemon=True,
        )
        self._log_thread.start()

        # Wait for health, watching for early process death
        deadline = time.monotonic() + settings.start_timeout_seconds
        while time.monotonic() < deadline:
            exit_code = self._process.poll()
            if exit_code is not None:
                self._report_dead_process(exit_code)
                self._process = None
                raise AppiumServerError(
                    f"Appium server exited during startup (exit code {exit_code}). "
                    f"See {self._log_file} for details."
                )
            status = fetch_status(settings.health_url(), timeout=1.0)
            if status is not None:
                self._started_by_us = True
                LOG.info(
                    "Appium server started successfully",
                    kv={
                        "pid": self._process.pid,
                        "url": settings.server_url(),
                        "version": _server_version(status),
                        "log_file": str(self._log_file),
                    },
                )
                return True
            time.sleep(_POLL_INTERVAL)

        # Startup timeout: clean up and raise with the log tail
        try:
            self._process.terminate()
        except OSError:
            pass
        self._process = None
        raise AppiumServerError(
            f"Appium server did not become healthy at {settings.server_url()} "
            f"within {settings.start_timeout_seconds}s.\n"
            f"Last lines of {self._log_file}:\n{self.log_tail(25)}"
        )

    def _report_dead_process(self, exit_code: int) -> None:
        LOG.error(
            "Appium server process died",
            kv={"exit_code": exit_code, "log_file": str(self._log_file)},
        )
        LOG.error(f"Server log tail:\n{self.log_tail(25)}")

    def log_tail(self, lines: int = 25) -> str:
        """Return the last ``lines`` of the captured server log ('' if none)."""
        if self._log_file is None or not self._log_file.exists():
            return "(no log captured yet)"
        try:
            content = self._log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(log not readable)"
        tail = content.strip().splitlines()[-lines:]
        return "\n".join(tail)

    def _consume_stdout(self) -> None:
        """Copy server stdout into appium_server.log, mirroring ERR/WARN."""
        if self._process is None or self._process.stdout is None:
            return
        handle = self._log_file.open("a", encoding="utf-8", errors="replace", buffering=1)
        try:
            for raw_line in self._process.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                handle.write(line + "\n")
                handle.flush()
                upper = line.upper()
                if "ERROR" in upper:
                    LOG.error(f"[appium-server] {line}")
                elif "WARN" in upper or "DEPRECAT" in upper:
                    LOG.warning(f"[appium-server] {line}")
                else:
                    LOG.debug(f"[appium-server] {line}")
        except Exception:  # pragma: no cover - best effort tailing
            pass
        finally:
            handle.flush()
            handle.close()

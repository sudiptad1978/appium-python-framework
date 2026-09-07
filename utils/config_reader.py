"""Configuration loading and resolution.

Reads, in this order of precedence (highest wins):

1. explicit arguments (e.g. ``--platform ios`` on the CLI)
2. environment variables (from the shell / CI or a local ``.env`` file)
3. ``config/settings.yaml`` for global settings
4. ``config/<platform>.yaml`` for the target device/app configuration

Only the *resolved* platform has its platform YAML loaded, which keeps
Android and iOS configuration strictly separated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from utils.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SUPPORTED_PLATFORMS = ("android", "ios")
PLATFORM_FILES = {"android": "android.yaml", "ios": "ios.yaml"}

# Load optional .env (never fails, never overrides real environment)
load_dotenv(PROJECT_ROOT / ".env", override=False)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _env_str(key: str, default: str = "") -> str:
    value = os.getenv(key, "").strip()
    return value if value else default


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def resolve_platform(cli_platform: str | None = None) -> str:
    """Return a validated platform name: CLI flag > APP_PLATFORM > android."""
    platform = (cli_platform or _env_str("APP_PLATFORM", "android")).strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ConfigError(
            f"Unsupported platform {platform!r}. Choose one of: "
            f"{', '.join(SUPPORTED_PLATFORMS)} (--platform flag or APP_PLATFORM env)."
        )
    return platform


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(
            f"Configuration file not found: {path}\n"
            f"Create it from the YAML templates or re-run the framework "
            f"creation script."
        )
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration file {path} must contain a YAML mapping.")
    return data


def _require(container: dict, key: str, source: str) -> object:
    if key not in container or container[key] is None:
        raise ConfigError(f"Missing required key {key!r} in {source}.")
    return container[key]


# ---------------------------------------------------------------------------
# settings object
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Fully resolved runtime settings for one test run."""

    platform: str
    device: dict = field(default_factory=dict)
    project_root: Path = PROJECT_ROOT

    # appium server
    host: str = "127.0.0.1"
    port: int = 4723
    base_path: str = ""
    binary: str = ""
    auto_start: bool = True
    external: bool = False
    start_timeout_seconds: int = 30
    stop_timeout_seconds: int = 10
    server_log_level: str = "info"
    use_drivers: list = field(default_factory=list)

    # paths (absolute)
    log_dir: Path = PROJECT_ROOT / "logs"
    screenshot_dir: Path = PROJECT_ROOT / "artifacts" / "screenshots"
    page_source_dir: Path = PROJECT_ROOT / "artifacts" / "page_source"

    # timeouts (seconds)
    timeout_default: int = 15
    timeout_short: int = 5
    timeout_long: int = 30

    # logging
    log_level: str = "INFO"

    # ------------------------------------------------------------------ #
    def server_url(self) -> str:
        """Base URL the Appium client connects to (no trailing slash)."""
        base = self.base_path.strip("/")
        return f"http://{self.host}:{self.port}" + (f"/{base}" if base else "")

    def health_url(self) -> str:
        """URL of the W3C ``/status`` endpoint used for health checks."""
        return f"{self.server_url()}/status"

    def resolve_app_path(self) -> str:
        """Absolute path to the app under test ('' when the app is installed
        on the device and app_path was left empty)."""
        raw = str(self.device.get("app_path", "") or "").strip()
        if not raw:
            return ""
        path = Path(raw)
        if not path.is_absolute():
            path = self.project_root / path
        return str(path)

    def summary(self) -> str:
        """One-line human readable summary used in logs and run banners."""
        udid = self.device.get("udid") or "-"
        return (
            f"platform={self.platform} device_name={self.device.get('device_name')!r} "
            f"udid={udid} app={self.device.get('app_path')!r} "
            f"appium={self.host}:{self.port}"
        )


def _load_device_config(platform: str) -> dict:
    path = CONFIG_DIR / PLATFORM_FILES[platform]
    data = _read_yaml(path)
    required = ("platform_name", "automation_name", "device_name")
    for key in required:
        _require(data, key, str(path))
    return data


def _merge_appium_settings(data: dict) -> dict:
    """Appium server settings from settings.yaml, overridden by APPIUM_* env vars.

    ``external``/``auto_start`` semantics:
    * external=True  -> the framework never starts/stops the server (CI,
      Appium Desktop, docker, grid...). APP_EXTERNAL=true forces this.
    * external=False and auto_start=True  -> start automatically if needed,
      stop at session end only if this run started it (default).
    * external=False and auto_start=False -> fail with clear guidance when
      no server is reachable.
    """
    appium = data.get("appium") or {}
    external_default = bool(appium.get("external", False))
    external = _env_bool("APP_EXTERNAL", external_default)
    return {
        "host": _env_str("APPIUM_HOST", str(appium.get("host", "127.0.0.1"))),
        "port": int(_env_str("APPIUM_PORT", str(appium.get("port", 4723)))),
        "base_path": str(appium.get("base_path", "") or "").strip(),
        "binary": _env_str("APPIUM_BINARY", str(appium.get("binary", "") or "")),
        "auto_start": bool(appium.get("auto_start", True)) if not external else False,
        "external": external,
        "start_timeout_seconds": int(appium.get("start_timeout_seconds", 30)),
        "stop_timeout_seconds": int(appium.get("stop_timeout_seconds", 10)),
        "server_log_level": str(appium.get("log_level", "info")).lower(),
        "use_drivers": list(appium.get("use_drivers") or []),
    }


def load_settings(platform: str | None = None) -> Settings:
    """Build a resolved :class:`Settings` for the given platform."""
    platform = resolve_platform(platform)
    settings_file = _read_yaml(CONFIG_DIR / "settings.yaml")
    device = _load_device_config(platform)
    appium = _merge_appium_settings(settings_file)

    # Environment overrides that target the device under test
    if _env_str("APP_DEVICE_NAME"):
        device["device_name"] = _env_str("APP_DEVICE_NAME")
    if _env_str("APP_UDID"):
        device["udid"] = _env_str("APP_UDID")
    if _env_str("APP_PATH"):
        device["app_path"] = _env_str("APP_PATH")
        device["_app_path_origin"] = "env"  # informational

    paths = settings_file.get("paths") or {}
    timeouts = settings_file.get("timeouts") or {}
    logging_cfg = settings_file.get("logging") or {}

    def _root_relative(raw: str) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path

    settings = Settings(
        platform=platform,
        device=device,
        host=appium["host"],
        port=appium["port"],
        base_path=appium["base_path"],
        binary=appium["binary"],
        auto_start=appium["auto_start"],
        external=appium["external"],
        start_timeout_seconds=appium["start_timeout_seconds"],
        stop_timeout_seconds=appium["stop_timeout_seconds"],
        server_log_level=appium["server_log_level"],
        use_drivers=appium["use_drivers"],
        log_dir=_root_relative(str(paths.get("logs", "logs"))),
        screenshot_dir=_root_relative(str(paths.get("screenshots", "artifacts/screenshots"))),
        page_source_dir=_root_relative(str(paths.get("page_source", "artifacts/page_source"))),
        timeout_default=int(timeouts.get("default", 15)),
        timeout_short=int(timeouts.get("short", 5)),
        timeout_long=int(timeouts.get("long", 30)),
        log_level=str(logging_cfg.get("level", "INFO")).upper(),
    )
    return settings

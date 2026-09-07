# config/ - what lives here and what you must change

| File | Purpose |
|---|---|
| `settings.yaml` | Global, platform-agnostic settings: Appium server address/behaviour, artifact paths, default timeouts, log level. |
| `android.yaml` | The Android *target*: device, app, package/activity, reset behaviour, extra capabilities. |
| `ios.yaml` | The iOS *target*: simulator/device, app, bundle id, signing (real devices), extra capabilities. |
| (no secrets!) | Credentials and per-job values belong in `.env` (see `.env.example`) or CI variables - never commit them. |

## Minimum edits before your first run

1. `config/android.yaml` -> `device_name` (yours from `adb devices`) and
   `app_path`/`app_package`+`app_activity`.
2. `config/ios.yaml` -> `device_name` (yours from `xcrun simctl list devices`)
   and `app_path`/`bundle_id`.
3. Optionally copy `.env.example` to `.env` for local overrides.

## Precedence (highest wins)

```
pytest/CLI flags  >  environment variables (.env / CI)  >  settings.yaml  >  <platform>.yaml
```

| Concern | CLI | Env var | YAML |
|---|---|---|---|
| Platform | `--platform ios` | `APP_PLATFORM` | `android` default |
| Server address | - | `APPIUM_HOST` / `APPIUM_PORT` | `appium.host` / `appium.port` |
| External server | `--external-server` (run_tests) | `APP_EXTERNAL=true` | `appium.external` |
| Appium binary | - | `APPIUM_BINARY` | `appium.binary` |
| Device | `--device-name` / `--udid` | `APP_DEVICE_NAME` / `APP_UDID` | `<platform>.device_name` / `udid` |
| App under test | - | `APP_PATH` | `<platform>.app_path` |
| Log level | - | `LOG_LEVEL` | `logging.level` |

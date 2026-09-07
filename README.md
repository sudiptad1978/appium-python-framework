# Appium Python Test Framework (Android + iOS)

A production-ready, pytest-based mobile test automation framework built on
**Appium 2.x**, the **Appium Python client (5.x/6.x)** and **Selenium 4**,
supporting **Android and iOS** from one code base.

```
Python 3.9+  |  Appium 2.x  |  Appium Python Client 5+/6+  |  pytest 8+
Page Object Model  |  W3C Actions + mobile: extensions  |  explicit waits  |  YAML/env config
```

The sample tests drive the free cross-platform demo app
**[TheApp](https://github.com/appium-pro/TheApp)** (login screen), so you
can run the suite end-to-end without writing an app first.

---

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Directory structure](#directory-structure)
3. [Prerequisites](#prerequisites)
4. [Step-by-step setup](#step-by-step-setup)
5. [Configuration - what to change](#configuration---what-to-change)
6. [Running the tests](#running-the-tests)
7. [How the Appium server lifecycle works](#how-the-appium-server-lifecycle-works)
8. [Gestures - usage & platform notes](#gestures---usage--platform-notes)
9. [Page objects - how to add a screen](#page-objects---how-to-add-a-screen)
10. [Logs & failure artifacts](#logs--failure-artifacts)
11. [Troubleshooting](#troubleshooting)
12. [Recommended next steps](#recommended-next-steps)

---

## Architecture overview

```
                 ┌────────────────────────────────────────────────┐
   pytest ──────►│ conftest.py                                    │
 (CLI options,   │  platform resolution, logging, fixtures,       │
  fixtures,      │  failure-artifact hooks                        │
  markers)       └───────────────┬────────────────────────────────┘
                                 │ appium_server fixture / driver fixture
                 ┌───────────────▼────────────────────────────────┐
                 │ drivers/                                       │
                 │  options_builder.py  (YAML → W3C capabilities) │
                 │  driver_factory.py   (session creation, errors)│
                 └───────────────┬────────────────────────────────┘
                                 │
                 ┌───────────────▼────────────────────────────────┐
                 │ utils/                                         │
                 │  appium_server.py   start/stop/reuse/detect    │
                 │  config_reader.py   YAML + env + CLI merge     │
                 │  waits.py  gestures.py  logger.py  screenshot  │
                 └───────────────┬────────────────────────────────┘
                                 │ driver
                 ┌───────────────▼────────────────────────────────┐
                 │ pages/  (Page Object Model)                    │
                 │  base_page.py  +  screen page classes          │
                 │  tests call BUSINESS actions, never locators   │
                 └────────────────────────────────────────────────┘
```

Design decisions (and why):

| Decision | Why |
|---|---|
| **One test code path for both platforms** | POM keeps app-behaviour logic shared; only *genuinely* platform-specific selectors (e.g. native alerts) branch on the platform - see `pages/login_page.py`. |
| **Explicit waits everywhere, zero hard sleeps** | `utils/waits.py` wraps `WebDriverWait`/EC and returns the instant a condition is true. Fast, stable, self-documenting timeouts. |
| **W3C Actions first, `mobile:` shortcuts where they win** | `TouchAction`/`MultiAction` are removed from Appium 2 and the Python client ≥ 4. Every gesture in `utils/gestures.py` uses W3C pointer actions or current `mobile:` commands (verified against the UiAutomator2/XCUITest driver sources). |
| **Typed capability options** | `UiAutomator2Options`/`XCUITestOptions` (client ≥ 3) replace the removed `desired_capabilities`; the builder enforces the `appium:` prefix rules of W3C/Appium 2. |
| **Config layering CLI > env > YAML** | Platform YAML files are isolated per platform; CI overrides device/app per job via env vars without touching git-tracked files. |
| **Session-scoped Appium server, started only when missing** | The suite probes the W3C `/status` endpoint first and reuses any running server; it only stops a server *it* started (see §7). |
| **Screenshots/page-source on every failure** | A single pytest hook captures artifacts for the whole suite - page classes never need bespoke failure handling. |
| **Runner script + pure pytest both supported** | `python run_tests.py --platform ios` is sugar over `pytest --platform ios`; CI can use either. |

### Structure notes vs. the "classic" skeleton

The layout keeps your requested structure and adds only what industry
frameworks need:

* `drivers/options_builder.py` keeps capability assembly out of the factory
  (single responsibility, unit-testable).
* `utils/errors.py` centralises exceptions so helpers never import pytest.
* `apps/` holds the (git-ignored) binaries under test; `config/` is
  data-only YAML; runtime output lives in `logs/` + `artifacts/` (git-ignored).
* `run_tests.py` is an optional ergonomic wrapper - it sets the same env
  vars `conftest.py` reads, so both entry points behave identically.

---

## Directory structure

```
appium-python-framework/
├── config/                  # data-only YAML configuration
│   ├── settings.yaml        #   Appium server, paths, timeouts, logging
│   ├── android.yaml         #   Android target (device, app, caps)
│   ├── ios.yaml             #   iOS target (simulator, app, signing)
│   └── README.md
├── drivers/                 # driver creation layer
│   ├── __init__.py
│   ├── options_builder.py   #   YAML → typed Appium options (W3C caps)
│   └── driver_factory.py    #   session creation, health check, rich errors
├── pages/                   # Page Object Model
│   ├── __init__.py
│   ├── base_page.py         #   shared toolbox (find/click/type/wait/gestures/…)
│   ├── home_page.py         #   TheApp home screen
│   ├── login_page.py        #   TheApp login screen (+ platform alert locators)
│   └── secret_page.py       #   TheApp post-login screen
├── tests/
│   └── test_login.py        # sample feature tests (valid/invalid/logout)
├── utils/                   # framework plumbing (no pytest imports)
│   ├── __init__.py
│   ├── appium_server.py     #   server start/stop/detect/reuse
│   ├── config_reader.py     #   CLI/env/YAML resolution
│   ├── errors.py            #   shared exception types
│   ├── gestures.py          #   W3C + mobile: gesture library
│   ├── logger.py            #   structured logging (suite.log)
│   ├── screenshot.py        #   screenshots + page source capture
│   └── waits.py             #   explicit-wait helpers
├── apps/                    # app binaries (git-ignored) + README
├── conftest.py              # pytest bootstrap & fixtures
├── pytest.ini
├── requirements.txt
├── run_tests.py             # optional convenience runner
├── .env.example
├── .gitignore
└── create_framework.py      # regeneration script (safe, idempotent)
```

---

## Prerequisites

| Tool | Version | Purpose | Verify with |
|---|---|---|---|
| Python | 3.9+ | framework runtime | `python3 --version` |
| Node.js + npm | 18+ LTS | Appium 2 server (and drivers) | `node --version` |
| Appium | **2.x** | automation server | `appium --version` |
| Appium drivers | `uiautomator2` / `xcuitest` | per-platform automation backends | `appium driver list` |
| Android: JDK | 17 (or 11 with AGP ≥ 7) | Android tooling | `java -version` |
| Android SDK | latest | emulator/adb/uiautomator | `adb --version` |
| iOS (macOS only) | Xcode 15+ incl. simulators | XCUITest/WDA builds | `xcodebuild -version` |
| macOS | 13+ | iOS testing requires macOS | `sw_vers` |

**Important:** Appium is a *server*; the drivers are separate npm packages it
loads. Appium 2 ships with **no** drivers - install them explicitly
(§ Setup, step 4).

---

## Step-by-step setup

### 1. Python environment

```bash
cd appium-python-framework
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
```

Verify: `python -c "import appium, selenium; print(appium.__version__)"`
(the client prints its version on import when asked - if the attribute is
absent you are on the expected ≥ 5.x line).

### 2. Appium server + drivers

```bash
npm install -g appium@2          # Appium 2.x line
appium --version                 # expect 2.x
appium driver install uiautomator2   # Android backend
appium driver install xcuitest       # iOS backend (macOS)
appium driver list               # both should show "installed"
```

### 3. Android setup

```bash
# 1) Android SDK env (add to ~/.zshrc / ~/.bashrc)
export ANDROID_HOME=$HOME/Library/Android/sdk        # macOS default
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator
source ~/.zshrc

# 2) Create an emulator (or use Android Studio AVD manager)
avdmanager create avd -n pixel_9 -k "system-images;android-35;google_apis;x86_64" --device "pixel_9"
emulator -avd pixel_9 &            # or open Android Studio

# 3) Confirm adb sees it and remember its serial
adb devices                        # -> emulator-5554   device
```

> Real device: enable *Developer options → USB debugging*, plug it in and
> use its `adb devices` serial as `udid`/`device_name` in
> `config/android.yaml`.

### 4. iOS setup (macOS only)

```bash
xcode-select --install              # if needed
xcrun simctl list devices available # note the exact name, e.g. "iPhone 15 Pro"
xcrun simctl boot "iPhone 15 Pro"   # optional: pre-boot the simulator
open -a Simulator
```

Appium builds WebDriverAgent automatically on the first session (can take a
few minutes). Real iPhones additionally need `xcode_org_id` +
`xcode_signing_id` in `config/ios.yaml` and a development profile installed.

### 5. Get the demo app (TheApp)

```bash
cd apps
curl -LO https://github.com/appium-pro/TheApp/releases/download/v1.12.0/TheApp.apk       # Android
curl -LO https://github.com/appium-pro/TheApp/releases/download/v1.12.0/TheApp.app.zip   # iOS
```

Or point `app_path` at **your** app and keep your own package/bundle ids.

### 6. Configure (edit only the values that are yours)

See the [Configuration](#configuration---what-to-change) section and
`config/README.md`. Minimal change set: the `device_name`, `app_path` and
package/bundle id values - every one of them is marked `CHANGE ME` in the
YAML with the discovery command right above it.

### 7. First smoke run

```bash
python run_tests.py --platform android --device-name emulator-5554 -m smoke
```

Expected: the runner banner (platform, device, server URL), automatic
Appium server start, session creation, tests, cleanup, and a summary. Then
run the full sample suite (below).

---

## Configuration - what to change

Values that MUST be customized for your project (all marked in the YAML):

| Placeholder | Where | Discover yours with | Purpose |
|---|---|---|---|
| `YOUR_DEVICE_NAME` | `android.yaml` `device_name` | `adb devices` | adb serial (`emulator-5554`) |
| `YOUR_APP_PATH` | `android.yaml` `app_path` | `ls apps/` | `.apk` path (or `APP_PATH` env) |
| `YOUR_APP_PACKAGE` / `YOUR_APP_ACTIVITY` | `android.yaml` | `adb shell pm list packages` / `aapt dump badging app.apk` | launch target when no `app_path` |
| `YOUR_DEVICE_NAME` | `ios.yaml` `device_name` | `xcrun simctl list devices` | simulator display name |
| `YOUR_APP_PATH` | `ios.yaml` `app_path` | `ls apps/` | `.app`/`.app.zip`/`.ipa` path |
| `YOUR_BUNDLE_ID` | `ios.yaml` `bundle_id` | Xcode target settings | installed-app launch |
| `YOUR_TEAM_ID` (real devices) | `ios.yaml` `xcode_org_id` | developer.apple.com | WDA signing |
| test accounts | `tests/test_login.py` | your test data | demo creds are TheApp's |

Everything else (server management, timeouts, artifact paths, log level)
already has sane defaults in `settings.yaml`.

### Environment variables

Copy `.env.example` to `.env` and adjust; all values are optional and only
override YAML defaults. The full list with defaults:

| Variable | Default | Meaning |
|---|---|---|
| `APP_PLATFORM` | `android` | target platform |
| `APP_EXTERNAL` | `false` | attach to an externally managed server |
| `APPIUM_HOST` / `APPIUM_PORT` | `127.0.0.1` / `4723` | server address |
| `APPIUM_BINARY` | (from `$PATH`) | absolute path to the appium executable |
| `APP_DEVICE_NAME` | (from YAML) | device/simulator override (CI) |
| `APP_UDID` | (from YAML) | udid override (CI) |
| `APP_PATH` | (from YAML) | app-under-test override (CI) |
| `LOG_LEVEL` | `INFO` | framework log verbosity |

---

## Running the tests

```bash
# Convenience runner (recommended for humans)
python run_tests.py                                    # Android, auto server
python run_tests.py --platform ios                     # iOS
python run_tests.py --external-server                  # reuse a running server
python run_tests.py --platform ios -k login -x         # pytest args pass through

# Pure pytest (recommended for CI) - identical behaviour
pytest --platform android
pytest --platform ios
APP_PLATFORM=ios pytest tests/ -m "not android"

# Device overrides
pytest --platform android --udid R58M1234567
pytest --platform ios --device-name "iPhone 15 Pro"
```

Both entry points read the same config layer; `run_tests.py` only sets the
environment variables for you.

---

## How the Appium server lifecycle works

`utils/appium_server.py` implements the whole lifecycle explicitly:

1. **Detection** - at session start the manager GETs the W3C
   `/status` endpoint (`http://host:port/status`). A *reachable status
   endpoint* - not a bare TCP probe - is the definition of "a server is
   running".
2. **Start (auto mode)** - nothing answers → the manager resolves the
   `appium` binary (config, `APPIUM_BINARY`, or `$PATH`) and launches
   `appium server --address … --port … --log-level info --log-no-colors`,
   streaming stdout into `logs/appium_server.log`. It then polls `/status`
   until healthy (default 30 s) and fails with the log tail if the process
   dies early.
3. **Reuse** - a server already answering is **never** restarted; the run
   logs "already running - reusing" and attaches. This also protects you
   from accidentally spawning a second instance on the same port.
4. **External mode** (`external: true` / `APP_EXTERNAL=true`) - the manager
   only *waits for and validates* the external server (Appium Desktop, a CI
   service, docker-compose, a grid). It never starts or stops it.
5. **Stop** - at session end the manager terminates the process **only if
   this run started it** (`started_by_us`). A reused or external server
   stays up for the next job - exactly what you want in CI.
6. **Failure reporting** - start/stop/reuse events are logged at INFO;
   server ERROR/WARN lines are mirrored into the suite log; startup failures
   embed the server log tail in the exception message.

### Log flow during a run

```
session start ──► [conftest] resolve platform/config → prepare dirs → setup logging
              ──► [appium_server] probe /status ── no ──► spawn server ──► poll /status ──► ready
              ──► [driver_factory] health check → build options → create session
per test      ──► [hooks] TEST START log … TEST FINISH log; on failure: screenshot + page source
session end   ──► driver.quit() → server.stop() (only if started by us)
```

---

## Gestures - usage & platform notes

All gestures live in `utils/gestures.py`; page objects expose thin
delegates. Engine: **W3C pointer actions** (uniform across drivers) with
**native `mobile:` commands** where they are the recommended API. No
deprecated TouchAction APIs anywhere.

```python
from utils import gestures  # or use BasePage delegates

# --- taps ---------------------------------------------------------------
gestures.tap_at(driver, 100, 320)            # raw coordinates (pixels)
gestures.tap_element(driver, element)        # element centre
gestures.double_tap_element(driver, element) # native mobile: doubleClickGesture / doubleTap
gestures.double_tap_at(driver, x, y)         # iOS note: native doubleTap is element-only
                                             #   -> transparent W3C fallback here
# --- long press ----------------------------------------------------------
gestures.long_press(driver, element=el, duration_seconds=1.2)
gestures.long_press(driver, x=200, y=600, duration_seconds=1.0)
# Android: mobile: longClickGesture (duration ms; >=500 ms = long click)
# iOS:     mobile: touchAndHold (duration seconds)

# --- swipe / scroll ------------------------------------------------------
# Direction = FINGER TRAVEL. swipe_up reveals content further DOWN the page.
gestures.swipe_up(driver)                    # full screen
gestures.swipe_between_coordinates(driver, 100, 500, 100, 200, duration_ms=600)
gestures.swipe_between_elements(driver, src_element, dst_element)
gestures.scroll(driver, 'up', element=list_view_element)   # scroll inside a list
page.scroll_to_element(driver, AppiumBy.ACCESSIBILITY_ID, 'row 42')  # swipe-until-visible
# ScrollView speed: duration 700-1000 ms = drag; 100-250 ms = flick feel.

# --- flick / fling -------------------------------------------------------
gestures.flick_up(driver)                    # fast W3C swipe (both platforms)
gestures.fling_android(driver, 'up')         # native velocity fling (Android only)

# --- drag & drop ---------------------------------------------------------
gestures.drag_and_drop(driver, source_element, target_element,
                       hold_seconds=1.0, move_duration_ms=800)

# --- pinch / zoom --------------------------------------------------------
gestures.zoom_in(driver, element=image_element)    # Android pinchOpenGesture,
                                                   # iOS mobile: pinch scale>1
gestures.zoom_out(driver)                          # pinchClose / scale<1
# Fallbacks to W3C two-finger pinches are attempted automatically.

# --- platform commands ---------------------------------------------------
gestures.back(driver)                       # Android system back (raises on iOS)
gestures.hide_keyboard(driver)              # safe: no-op when keyboard is hidden
```

Direction semantics and platform differences worth remembering:

| Gesture | Android (UiAutomator2) | iOS (XCUITest) |
|---|---|---|
| tap | W3C click / `mobile: clickGesture` | W3C; `mobile: tap` exists for special cases |
| double tap | `mobile: doubleClickGesture` (element **or** coords) | `mobile: doubleTap` (**element only**; coords use W3C) |
| long press | `mobile: longClickGesture`, duration in **ms**, ≥ 500 ms | `mobile: touchAndHold`, duration in **seconds** |
| swipe w/ coords | `mobile: swipeGesture`/`dragGesture` or W3C | `mobile: dragFromToForDuration` or W3C (this framework uses W3C) |
| directional swipe | `mobile: swipeGesture {direction}` | `mobile: swipe {direction}` (no coordinates) |
| fling | `mobile: flingGesture` (velocity) | no native equivalent → `flick_*` W3C |
| pinch | `mobile: pinchOpenGesture`/`pinchCloseGesture` (`percent`) | `mobile: pinch {scale, velocity}` |
| back | `driver.back()` | **no system back** - use in-app navigation |
| hide keyboard | hides via KEYCODE_BACK, only when shown | `strategy=default/pressKey/swipeDown/tapOutside` |

---

## Page objects - how to add a screen

1. **Locators**: prefer accessibility ids - they are identical on both
   platforms. Use tuples for platform-only strategies
   (`AppiumBy.ANDROID_UIAUTOMATOR`, `AppiumBy.IOS_PREDICATE`, XPath...).
2. **Actions, not clicks**: expose business verbs (`login(username, pw)`,
   `add_item_to_cart(sku)`) that internally wait + act + wait for the next
   state.
3. **Navigation returns pages**: `HomePage.navigate_to_login()` returns a
   ready `LoginPage` - tests read like the user journey.
4. **Wait for state, not time**: after an action, wait for the *result*
   screen element (`wait_logged_in_as`), never `sleep`.

Example (mirrors `tests/test_login.py`):

```python
def test_valid_credentials_reach_secret_area(self, driver):
    secret = (HomePage(driver)
              .navigate_to_login()
              .login_success("alice", "mypassword"))       # waits internally
    assert secret.is_logged_in_as("alice")
```

---

## Logs & failure artifacts

| Path | Content |
|---|---|
| `logs/suite.log` | structured framework log: config summary, server lifecycle, driver creation, per-test start/end, element waits, gestures, failures |
| `logs/appium_server.log` | raw stdout of the Appium server process (the first place to look when a session fails) |
| `artifacts/screenshots/*.png` | one per failing test: `<test>_<platform>_<timestamp>.png` |
| `artifacts/page_source/*.xml` | the view hierarchy at failure time (locator debugging gold) |

Failure artifacts are written by a global pytest hook
(`pytest_runtest_makereport`), so *every* test gets them for free. Page
classes can also capture deliberately via `page.take_screenshot()`.

Console output is human-friendly; the file logs are machine-readable
`key=value` lines, e.g.:

```
2026-09-07 20:41:03 | INFO     | driver_factory | Driver created successfully | session_id=1e2f… platform=android desired=emulator-5554
2026-09-07 20:41:05 | INFO     | conftest       | TEST FINISH | test=test_valid_credentials_reach_secret_area outcome=passed duration_s=4.2
```

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `The 'appium' executable was not found on $PATH` | Install Appium (`npm install -g appium@2`) or set `APPIUM_BINARY` to the absolute path (`appium.cmd` on Windows). |
| `Appium server exited during startup` + log tail | Port already in use by another process (`lsof -i :4723`); or a driver failed to load (check `logs/appium_server.log`). |
| `External Appium server not reachable` | Your CI/desktop server isn't up yet or host/port mismatch. |
| `... driver uiautomator2 ... not installed` (session creation) | `appium driver install uiautomator2` / `xcuitest`. The error text tells you this. |
| `Could not create an Android session` | No device connected: `adb devices`; or `device_name`/`udid` mismatch; app path wrong. |
| iOS session takes minutes / `xcodebuild` errors | First WDA build is slow - be patient once; then check Xcode license (`sudo xcodebuild -license accept`) and simulator runtime availability. |
| `No Appium server reachable` at driver creation | auto_start disabled and no external server: enable `auto_start` or start one. |
| Element timeouts that worked in Appium 1 | Bare capabilities (`deviceName:`) are ignored by Appium 2 - this framework always prefixes `appium:`; the options builder does it for you. |
| Keyboard not hiding | Android only hides when shown (safe guard built in); iOS supports `strategy="swipeDown"`. |
| Gesture does nothing on iOS lists | iOS needs real inertial scrolling for some ScrollViews; increase `duration_ms` or use `flick_*`. |
| StaleElementReference in loops | Re-resolve the element each iteration (our scroll helpers do); never cache list items across swipes. |

### Debugging recipe

1. Read `logs/appium_server.log` tail - the server states the real reason a
   session/capability failed.
2. Check the failure screenshot + XML page source in `artifacts/`.
3. Raise verbosity: `LOG_LEVEL=DEBUG pytest --platform android -k your_test`.

---

## Recommended next steps

1. **Point it at your app**: replace the TheApp pages with your screens and
   move test data (accounts, SKUs) into config/`.env` or a data module.
2. **CI matrix**: two jobs (Android/iOS) - each sets `APP_PLATFORM`,
   `APP_DEVICE_NAME`/`APP_UDID` and `APP_PATH`; `APP_EXTERNAL=true` when
   Appium runs as a service in the pipeline.
3. **Parallelism**: pytest-xdist with one device per worker
   (`APP_UDID`/`APP_DEVICE_NAME` per worker via `pytest --dist`), or shard
   by marker. (The session-scoped fixtures are per-process, which is what
   xdist needs.)
4. **Reports**: pytest-html / Allure; wire `pytest_terminal_summary` or a
   hook to upload `artifacts/` to your CI.
5. **Hybrid/webview apps**: add a context helper (driver.context switching)
   following the same POM pattern; capabilities like
   `appium:chromedriverExecutable` go in `additional_capabilities`.
6. **App state hygiene**: decide noReset vs fullReset per environment
   (fast local vs clean CI) via env override instead of editing YAML.
7. **Version pinning**: pin `appium-python-client`, `selenium` and - in CI -
   the Appium driver versions (`appium driver install uiautomator2@<ver>`).
8. **Accessibility checks**: add assertions on the accessibility snapshot to
   catch a11y regressions alongside functional ones.

# The `apps/` directory is for the application binaries under test
# (YOUR .apk / .app / .app.zip / .ipa files). They are git-ignored on purpose:
# binaries do not belong in source control - download/build them in CI.

# Free demo application used by the example tests:
#   TheApp  -> https://github.com/appium-pro/TheApp/releases
# Android: TheApp.apk       (app_package: com.appiumpro.the_app)
# iOS:     TheApp.app.zip   (bundle_id:   com.appiumpro.the_app)

# Example download (choose YOUR platform):
#   curl -LO https://github.com/appium-pro/TheApp/releases/download/v1.12.0/TheApp.apk
#   curl -LO https://github.com/appium-pro/TheApp/releases/download/v1.12.0/TheApp.app.zip

# Then point config/android.yaml (app_path: apps/TheApp.apk) or
# config/ios.yaml (app_path: apps/TheApp.app.zip) at the file.

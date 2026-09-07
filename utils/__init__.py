"""Shared utilities for the mobile test framework (logging, config, waits,
gestures, screenshots, Appium server management).

Modules in this package must not import from ``pages``, ``drivers`` or pytest
so they stay reusable from scripts such as ``run_tests.py``.
"""

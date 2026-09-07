"""Driver layer: platform capability builders and the driver factory.

``drivers/`` has no external dependency on pytest, so the same factory can
be reused from CI scripts, one-off device checks or parallel executors.
"""

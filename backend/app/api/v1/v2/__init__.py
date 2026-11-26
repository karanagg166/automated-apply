"""Python v2 control plane REST package: shared dependencies (``deps``) and the topic sub-routers
(``routers``). ``backend.app.api.v1.automation_v2`` composes them into the single ``/api/v1/v2`` router.

Kept import-free on purpose: sub-modules import their siblings directly (no package-level cycles).
"""

"""Synthetic OS telemetry only; these cases prove no locked-screen execution."""

from backend.scripts.monitor_naukri_acceptance import lock_observation


def test_lock_monitor_requires_unambiguous_owner_session():
    assert (
        lock_observation(
            [
                {
                    "IOConsoleUsers": [
                        {"kCGSSessionUserIDKey": 501, "CGSSessionScreenIsLocked": True}
                    ]
                }
            ],
            501,
        )
        == "LOCKED"
    )
    assert (
        lock_observation(
            [
                {
                    "IOConsoleUsers": [
                        {"kCGSSessionUserIDKey": 501, "CGSSessionScreenIsLocked": False}
                    ]
                }
            ],
            501,
        )
        == "UNLOCKED"
    )
    for document in [
        {},
        [
            {
                "IOConsoleUsers": [
                    {"kCGSSessionUserIDKey": 502, "CGSSessionScreenIsLocked": True}
                ]
            }
        ],
        [{"IOConsoleUsers": [{"kCGSSessionUserIDKey": 501}]}],
    ]:
        assert lock_observation(document, 501) == "UNKNOWN"

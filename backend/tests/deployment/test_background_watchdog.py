import os

from apps.background.watchdog import heartbeat, is_fresh


def test_background_watchdog_requires_a_recent_heartbeat(tmp_path) -> None:
    path = tmp_path / "heartbeat"

    assert is_fresh(path, 60) is False
    heartbeat(path)
    assert is_fresh(path, 60) is True
    os.utime(path, (0, 0))
    assert is_fresh(path, 60) is False

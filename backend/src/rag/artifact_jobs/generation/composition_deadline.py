"""Deadline handling shared by artifact composition stages."""

from __future__ import annotations

from contextlib import contextmanager
import signal
import threading


@contextmanager
def _section_deadline(seconds: float | None):
    if (
        not seconds
        or threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "SIGALRM")
    ):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def raise_timeout(_signum, _frame) -> None:
        raise TimeoutError("artifact section composition timed out")

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])

"""Single source of 'now', so tests can fast-forward time (sessions, reminders)."""
import time


def now() -> int:
    return int(time.time())

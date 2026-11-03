"""In-memory, bounded watch signal for temporary fast CPU updates.

The UI can request a short-lived watch when CPU Details is visible.
Only verified owner POSTs may refresh the lease. The lease does not
grant control of the computer and does not persist across hub restarts.
"""

from __future__ import annotations

import threading
import time


class CPUWatch:
    def __init__(self, ttl_seconds: float = 7.0):
        if not 3 <= ttl_seconds <= 30:
            raise ValueError("Invalid CPU watch lease duration")
        self.ttl_seconds = ttl_seconds
        self._last_touch = 0.0
        self._lock = threading.Lock()

    def touch(self) -> None:
        with self._lock:
            self._last_touch = time.monotonic()

    def active(self) -> bool:
        with self._lock:
            last = self._last_touch
        return last > 0 and 0 <= time.monotonic() - last < self.ttl_seconds

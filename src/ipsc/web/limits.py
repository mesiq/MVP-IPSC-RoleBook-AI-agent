"""Protecting the free LLM quota and the small server: a per-visitor rate limit and a cap on parallel jobs."""
import threading
import time
from collections import defaultdict, deque

from ..settings import MAX_PARALLEL_JOBS, QUEUE_WAIT_SECONDS, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS


class RateLimiter:
    """Allows `max_requests` per visitor in a sliding window of `window` seconds."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window: float = RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window = window
        self._seen = defaultdict(deque)  # visitor -> times of recent requests
        self._lock = threading.Lock()

    def allow(self, visitor: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = self._seen[visitor]
            while recent and now - recent[0] > self.window:
                recent.popleft()
            if len(recent) >= self.max_requests:
                return False
            recent.append(now)
            if len(self._seen) > 10_000:  # forget visitors that have gone quiet
                for key in [k for k, v in self._seen.items() if not v or now - v[-1] > self.window]:
                    del self._seen[key]
            return True


class JobSlots:
    """At most `size` jobs run at once; others wait a little and then give up."""

    def __init__(self, size: int = MAX_PARALLEL_JOBS, wait: float = QUEUE_WAIT_SECONDS):
        self._slots = threading.BoundedSemaphore(size)
        self._wait = wait

    def acquire(self) -> bool:
        return self._slots.acquire(timeout=self._wait)

    def release(self) -> None:
        self._slots.release()

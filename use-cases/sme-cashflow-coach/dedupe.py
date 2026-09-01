"""In-memory WhatsApp message-id dedupe to ignore Meta webhook retries."""

from __future__ import annotations

import time
from collections import OrderedDict


class RecentMessageIds:
    """TTL set so the same inbound WhatsApp message is processed only once."""

    def __init__(self, ttl_seconds: float = 600.0, max_size: int = 2000) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._items: OrderedDict[str, float] = OrderedDict()

    def _purge(self, now: float) -> None:
        while self._items:
            _key, seen_at = next(iter(self._items.items()))
            if now - seen_at <= self._ttl:
                break
            self._items.popitem(last=False)

    def seen_or_add(self, message_id: str) -> bool:
        """Return True if this id was already processed."""
        if not message_id:
            return False
        now = time.monotonic()
        self._purge(now)
        if message_id in self._items:
            self._items.move_to_end(message_id)
            self._items[message_id] = now
            return True
        self._items[message_id] = now
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)
        return False

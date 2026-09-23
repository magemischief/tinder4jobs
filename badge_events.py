"""In-process broadcast broker for live badge notifications."""

from __future__ import annotations

import queue
import threading
from collections import defaultdict


class BadgeEventBroker:
    """Fan badge events out to every active subscriber for a user."""

    def __init__(self, queue_size: int = 20):
        self._queue_size = queue_size
        self._subscribers: dict[int, set[queue.Queue]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, user_id: int) -> queue.Queue:
        subscriber = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers[user_id].add(subscriber)
        return subscriber

    def unsubscribe(self, user_id: int, subscriber: queue.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(user_id)
            if not subscribers:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(user_id, None)

    def publish(self, user_id: int, badge: dict) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(user_id, ()))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(badge)
            except queue.Full:
                # A stalled browser should not block action requests. Retain the
                # newest notifications in its bounded queue.
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                subscriber.put_nowait(badge)

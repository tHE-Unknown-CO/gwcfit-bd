"""One PostgreSQL listener per API worker; only committed changes are broadcast."""
import asyncio
import logging
import threading
from collections import defaultdict
from contextlib import contextmanager

import psycopg

from app.database.session import engine

logger = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self):
        self.subscribers = defaultdict(set)
        self.sync_needed = asyncio.Event()
        self.push_needed = asyncio.Event()
        self.stop = threading.Event()

    @contextmanager
    def subscribe(self, user_id):
        queue = asyncio.Queue(maxsize=1)
        self.subscribers[str(user_id)].add(queue)
        try:
            yield queue
        finally:
            self.subscribers[str(user_id)].discard(queue)
            if not self.subscribers[str(user_id)]:
                self.subscribers.pop(str(user_id), None)

    def publish(self, channel, user_id):
        if channel == "pulsefit_platform_events":
            self.sync_needed.set()
            return
        self.push_needed.set()
        for queue in self.subscribers.get(user_id, ()):
            if queue.empty():
                queue.put_nowait(True)

    def listen(self, loop):
        # A blocking listener thread also supports Windows' default event loop.
        params = engine.url.translate_connect_args(username="user", database="dbname")
        params.update(engine.url.query)
        while not self.stop.is_set():
            try:
                with psycopg.connect(**params, autocommit=True, connect_timeout=5) as conn:
                    conn.execute("LISTEN pulsefit_notifications")
                    conn.execute("LISTEN pulsefit_platform_events")
                    loop.call_soon_threadsafe(self._reconnected)
                    while not self.stop.is_set():
                        for event in conn.notifies(timeout=1, stop_after=100):
                            loop.call_soon_threadsafe(self.publish, event.channel, event.payload)
            except Exception:
                logger.exception("Live notification listener disconnected; retrying")
                self.stop.wait(2)

    def _reconnected(self):
        self.sync_needed.set()
        self.push_needed.set()
        for user_id in list(self.subscribers):
            self.publish("pulsefit_notifications", user_id)

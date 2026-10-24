import asyncio
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.services.notification_realtime import NotificationHub


def test_live_hub_isolates_users_coalesces_events_and_cleans_up():
    async def check():
        hub = NotificationHub()
        with hub.subscribe("a") as a, hub.subscribe("b") as b:
            hub.publish("pulsefit_notifications", "a")
            hub.publish("pulsefit_notifications", "a")
            assert a.qsize() == 1
            assert b.empty()
            assert hub.push_needed.is_set()
            hub.publish("pulsefit_platform_events", "sync")
            assert hub.sync_needed.is_set()
            assert b.empty()
        assert not hub.subscribers
    asyncio.run(check())


def test_live_socket_authenticates_first_frame_and_pushes_user_changes(monkeypatch):
    from app.api.v1 import notifications
    def authenticate(token):
        if token != "valid":
            raise HTTPException(status_code=401)
        return "test-user", time.time() + 60
    monkeypatch.setattr(notifications, "_authenticate_socket", authenticate)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/notifications/live", headers={"Origin": "http://localhost:8081"}) as socket:
            socket.send_json({"access_token": "valid"})
            assert socket.receive_json() == {"type": "ready"}
            client.portal.call(app.state.notification_hub.publish, "pulsefit_notifications", "test-user")
            assert socket.receive_json() == {"type": "notifications_changed"}


@pytest.mark.parametrize("message", [{}, {"access_token": "invalid"}, {"access_token": 123}, []])
def test_live_socket_rejects_invalid_authentication(monkeypatch, message):
    from app.api.v1 import notifications
    def reject(token):
        raise HTTPException(status_code=401)
    monkeypatch.setattr(notifications, "_authenticate_socket", reject)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/notifications/live") as socket:
            socket.send_json(message)
            with pytest.raises(WebSocketDisconnect) as exc:
                socket.receive_json()
            assert exc.value.code == 4401


def test_live_socket_rejects_untrusted_browser_origins():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/v1/notifications/live", headers={"Origin": "https://untrusted.example"}):
                pass
        assert exc.value.code == 4403

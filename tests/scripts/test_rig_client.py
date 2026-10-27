"""The rig's HAClient against a local stub of HA's WebSocket and REST API, so a live run isn't its first test."""

import asyncio
import json

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from tests.rig.client import HAClient, HAError

BRIDGE_INFO = json.dumps({"config": {"devices": {"0x01": {"hue_native_control": True}}}})
STATES = {"switch.plug": {"entity_id": "switch.plug", "state": "off", "attributes": {}}}


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "auth_required"})
    auth = await ws.receive_json()
    await ws.send_json({"type": "auth_ok" if auth["access_token"] == "token" else "auth_invalid"})
    subscription = None
    async for message in ws:
        if message.type != WSMsgType.TEXT:
            break
        msg = message.json()
        if msg["type"] == "subscribe_events":
            subscription = msg["id"]
            await ws.send_json({"id": msg["id"], "type": "result", "success": True, "result": None})
        elif msg["type"] == "mqtt/subscribe":
            await ws.send_json({"id": msg["id"], "type": "result", "success": True, "result": None})
            retained = {"topic": msg["topic"], "payload": BRIDGE_INFO}
            await ws.send_json({"id": msg["id"], "type": "event", "event": retained})
        elif msg["type"] == "unsubscribe_events":
            await ws.send_json({"id": msg["id"], "type": "result", "success": True, "result": None})
            # HA can still deliver a message that was in flight for the closed subscription.
            late = {"topic": "zigbee2mqtt/bridge/info", "payload": BRIDGE_INFO}
            await ws.send_json({"id": msg["subscription"], "type": "event", "event": late})
        elif msg["service"] == "fail":
            error = {"code": "home_assistant_error", "message": "nope", "translation_key": "all_targets_failed"}
            await ws.send_json({"id": msg["id"], "type": "result", "success": False, "error": error})
        else:
            result = {"response": {"ok": msg["service_data"]}}
            await ws.send_json({"id": msg["id"], "type": "result", "success": True, "result": result})
            new_state = {"entity_id": "switch.plug", "state": "on", "attributes": {}}
            event = {"event_type": "state_changed", "data": {"entity_id": "switch.plug", "new_state": new_state}}
            await asyncio.sleep(0.05)
            await ws.send_json({"id": subscription, "type": "event", "event": event})
    return ws


async def state(request: web.Request) -> web.Response:
    if (entity := STATES.get(request.match_info["entity_id"])) is None:
        return web.Response(status=404)
    return web.json_response(entity)


@pytest.fixture
async def client(socket_enabled):
    app = web.Application()
    app.router.add_get("/api/websocket", websocket)
    app.router.add_get("/api/states/{entity_id}", state)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    ha = HAClient(str(server.make_url("")), "token")
    await ha.connect()
    yield ha
    await ha.close()
    await server.close()


async def test_call_service_returns_response_and_wait_for_sees_the_event(client: HAClient):
    response = await client.call_service("x", "turn_on", {"entity_id": "switch.plug"}, return_response=True)
    assert response == {"ok": {"entity_id": "switch.plug"}}
    state = await client.wait_for("switch.plug", lambda s: s is not None and s["state"] == "on", timeout=2)
    assert state["state"] == "on"


async def test_failed_call_raises_with_translation_key(client: HAClient):
    with pytest.raises(HAError) as err:
        await client.call_service("x", "fail", {})
    assert err.value.translation_key == "all_targets_failed"


async def test_wait_for_times_out_and_get_state_handles_404(client: HAClient):
    with pytest.raises(TimeoutError):
        await client.wait_for("switch.plug", lambda s: s is not None and s["state"] == "on", timeout=0.2)
    assert await client.get_state("switch.missing") is None


async def test_mqtt_reads_and_a_late_message_leave_the_connection_working(client: HAClient):
    assert await client.z2m_device_options("0x01") == {"hue_native_control": True}
    assert await client.z2m_device_options("0x02") == {}
    response = await client.call_service("x", "turn_on", {"entity_id": "switch.plug"}, return_response=True)
    assert response == {"ok": {"entity_id": "switch.plug"}}

"""The rig's HueBridge against a local stub of the bridge's CLIP v2 API."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.rig.bridge import BridgeError, HueBridge


async def serve(received: list, status: int = 200, reply: dict | None = None) -> TestServer:
    async def put(request: web.Request) -> web.Response:
        received.append((request.path, request.headers.get("hue-application-key"), await request.json()))
        return web.json_response(reply if reply is not None else {"data": [{"rid": "x"}], "errors": []}, status=status)

    app = web.Application()
    app.router.add_put("/clip/v2/resource/{kind}/{rid}", put)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    return server


def bridge_for(server: TestServer) -> HueBridge:
    bridge = HueBridge(f"{server.host}:{server.port}", "key")
    bridge.base = f"http://{server.host}:{server.port}/clip/v2/resource"
    return bridge


async def test_put_sends_the_body_to_the_resource_with_the_app_key(socket_enabled):
    received: list = []
    server = await serve(received)
    bridge = bridge_for(server)
    try:
        await bridge.put("light", "abc", {"on": {"on": True}})
    finally:
        await bridge.close()
        await server.close()
    assert received == [("/clip/v2/resource/light/abc", "key", {"on": {"on": True}})]


@pytest.mark.parametrize(
    ("status", "reply", "message"),
    [
        (200, {"errors": [{"description": "invalid body"}]}, "got 200: invalid body"),
        (403, {"errors": [{"description": "unauthorized user"}]}, "got 403: unauthorized user"),
        (500, {}, "got 500"),
    ],
)
async def test_put_raises_on_an_http_error_or_a_listed_error(socket_enabled, status, reply, message):
    server = await serve([], status, reply)
    bridge = bridge_for(server)
    try:
        with pytest.raises(BridgeError, match=message):
            await bridge.put("light", "abc", {})
    finally:
        await bridge.close()
        await server.close()


async def test_put_raises_when_the_bridge_cannot_be_reached(socket_enabled):
    server = await serve([])
    bridge = bridge_for(server)
    await server.close()
    try:
        with pytest.raises(BridgeError, match="PUT light/abc"):
            await bridge.put("light", "abc", {})
    finally:
        await bridge.close()

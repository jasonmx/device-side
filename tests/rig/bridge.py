"""A small Hue bridge client for rig tests: CLIP v2 writes made behind Home Assistant's back.

A rig case uses it to act as another actor (the Hue app, a dimmer, a motion rule), so Device Side sees a change it
did not make and Home Assistant did not send.
"""

import aiohttp

REQUEST_TIMEOUT_S = 10


class BridgeError(Exception):
    """A bridge write the bridge refused, or could not be made."""


class HueBridge:
    def __init__(self, host: str, app_key: str):
        self.base = f"https://{host}/clip/v2/resource"
        self.headers = {"hue-application-key": app_key}
        self._session: aiohttp.ClientSession | None = None

    async def put(self, resource_type: str, resource_id: str, body: dict) -> None:
        """PUT `body` to the resource; raises BridgeError on an HTTP error or any error the bridge lists."""
        if self._session is None:
            # The bridge's certificate is self-signed; the system resolver, as HAClient's, resolves mDNS names.
            connector = aiohttp.TCPConnector(ssl=False, resolver=aiohttp.ThreadedResolver())
            self._session = aiohttp.ClientSession(
                connector=connector, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
            )
        url = f"{self.base}/{resource_type}/{resource_id}"
        try:
            async with self._session.put(url, json=body) as response:
                reply = await response.json(content_type=None)
                status = response.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise BridgeError(f"PUT {resource_type}/{resource_id}: {type(err).__name__}: {err}") from None
        listed = reply.get("errors", []) if isinstance(reply, dict) else []
        errors = [error.get("description", error) for error in listed]
        if status >= 400 or errors:
            raise BridgeError(f"PUT {resource_type}/{resource_id} got {status}: {'; '.join(map(str, errors))}")

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

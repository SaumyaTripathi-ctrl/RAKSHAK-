"""The hub's 4G/MQTT link: real MQTT over TLS, or an in-memory stand-in for tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import ssl
from collections.abc import Awaitable, Callable
from typing import Protocol

log = logging.getLogger("rakshak.sim.uplink")

CommandHandler = Callable[[dict], Awaitable[None]]


class UplinkDown(ConnectionError):
    """Publishing while there is no network (the hub keeps the record in its queue)."""


class Uplink(Protocol):
    connected: bool

    async def connect(self) -> None: ...
    async def drop(self) -> None: ...  # lose the network abruptly (no MQTT DISCONNECT)
    async def close(self) -> None: ...
    async def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None: ...
    def set_command_handler(self, handler: CommandHandler) -> None: ...


def will_message(hub_id: str) -> tuple[str, str]:
    """MQTT last-will: what the broker publishes when the hub vanishes without saying goodbye."""
    return f"rakshak/{hub_id}/events", json.dumps({"type": "status", "online": False})


class MemoryUplink:
    """In-process uplink: published messages go to ``sink(topic, payload)`` while connected.

    ``lose_will=True`` mimics the broker publishing the last-will on an abrupt drop."""

    def __init__(
        self,
        hub_id: str,
        sink: Callable[[str, bytes], Awaitable[None]] | None = None,
        *,
        publish_will_on_drop: bool = True,
    ) -> None:
        self.hub_id = hub_id
        self.sink = sink
        self.connected = False
        self.published: list[tuple[str, bytes]] = []
        self._handler: CommandHandler | None = None
        self._will = publish_will_on_drop

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._handler = handler

    async def connect(self) -> None:
        self.connected = True

    async def drop(self) -> None:
        if not self.connected:
            return
        self.connected = False
        if self._will and self.sink is not None:
            topic, payload = will_message(self.hub_id)
            await self.sink(topic, payload.encode())

    async def close(self) -> None:
        self.connected = False

    async def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None:
        if not self.connected:
            raise UplinkDown("no network")
        data = payload.encode() if isinstance(payload, str) else bytes(payload)
        self.published.append((topic, data))
        if self.sink is not None:
            await self.sink(topic, data)

    async def deliver_command(self, cmd: dict) -> None:
        """Broker -> hub (the backend's publisher calls this in tests)."""
        if self._handler is not None and self.connected:
            await self._handler(cmd)


class MqttUplink:
    """aiomqtt client with TLS, a persistent session (commands queue while offline) and a last-will."""

    def __init__(
        self,
        hub_id: str,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        ca_file: str | None,
        tls: bool = True,
        keepalive: int = 10,
    ) -> None:
        self.hub_id, self.host, self.port = hub_id, host, port
        self.username, self.password, self.ca_file, self.tls = username, password, ca_file, tls
        self.keepalive = keepalive
        self.connected = False
        self._client = None
        self._rx: asyncio.Task | None = None
        self._handler: CommandHandler | None = None

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._handler = handler

    async def connect(self) -> None:
        import aiomqtt

        topic, payload = will_message(self.hub_id)
        client = aiomqtt.Client(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            identifier=f"sim-{self.hub_id}",
            clean_session=False,
            keepalive=self.keepalive,
            tls_params=aiomqtt.TLSParameters(ca_certs=self.ca_file, cert_reqs=ssl.CERT_REQUIRED)
            if self.tls
            else None,
            will=aiomqtt.Will(topic=topic, payload=payload, qos=1),
        )
        await client.__aenter__()
        await client.subscribe(f"rakshak/{self.hub_id}/cmd", qos=1)
        self._client = client
        self._rx = asyncio.create_task(self._listen(client))
        self.connected = True

    async def _listen(self, client) -> None:
        try:
            async for msg in client.messages:
                if self._handler is None:
                    continue
                try:
                    await self._handler(json.loads(bytes(msg.payload)))
                except (ValueError, TypeError):
                    log.warning("ignoring malformed command")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # connection lost
            log.info("%s mqtt receive loop ended: %s", self.hub_id, exc)
            self.connected = False

    async def drop(self) -> None:
        """Abrupt loss: close the TCP socket without DISCONNECT so the broker publishes the last-will."""
        client, self._client, self.connected = self._client, None, False
        if client is None:
            return
        if self._rx:
            self._rx.cancel()
        with contextlib.suppress(Exception):
            sock = client._client.socket()  # paho's underlying socket
            if sock is not None:
                # FIN without an MQTT DISCONNECT: the broker publishes the last-will. Do not close() the fd here:
                # asyncio still has it registered, and on Windows select() then fails on the dead socket.
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.__aexit__(None, None, None), 2)

    async def close(self) -> None:
        client, self._client, self.connected = self._client, None, False
        if self._rx:
            self._rx.cancel()
        if client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.__aexit__(None, None, None), 2)

    async def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> None:
        if not self.connected or self._client is None:
            raise UplinkDown("no network")
        try:
            await self._client.publish(topic, payload, qos=qos)
        except Exception as exc:
            self.connected = False
            raise UplinkDown(str(exc)) from exc

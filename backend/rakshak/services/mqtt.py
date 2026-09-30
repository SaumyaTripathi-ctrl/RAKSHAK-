"""MQTT bridge: subscribes to hub telemetry/events (QoS 1, persistent session) and publishes commands."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from typing import Protocol

import aiomqtt

from ..config import Settings
from .ingest import Ingestor

log = logging.getLogger("rakshak.mqtt")

TELEMETRY = "rakshak/+/telemetry"
EVENTS = "rakshak/+/events"


class CommandPublisher(Protocol):
    async def publish(self, topic: str, payload: bytes, qos: int = 1) -> None: ...


class NullPublisher:
    """Used when MQTT is disabled: commands fail loudly instead of pretending to be sent."""

    async def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        raise RuntimeError("MQTT is disabled (RAKSHAK_MQTT_ENABLED=false)")


def parse_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "rakshak" and parts[2] in ("telemetry", "events", "cmd"):
        return parts[1], parts[2]
    return None


class MqttBridge:
    def __init__(self, settings: Settings, ingestor: Ingestor) -> None:
        self.settings = settings
        self.ingestor = ingestor
        self._client: aiomqtt.Client | None = None
        self._connected = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.messages_seen = 0

    # -- lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mqtt-bridge")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout)

    def _tls_params(self) -> aiomqtt.TLSParameters | None:
        if not self.settings.mqtt_tls:
            return None
        return aiomqtt.TLSParameters(
            ca_certs=self.settings.mqtt_ca_file, cert_reqs=ssl.CERT_REQUIRED
        )

    # -- main loop
    async def _run(self) -> None:
        s = self.settings
        delay = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=s.mqtt_host,
                    port=s.mqtt_port,
                    username=s.mqtt_username,
                    password=s.mqtt_password,
                    identifier=s.mqtt_client_id,
                    clean_session=False,  # persistent session: broker queues QoS-1 while we are down
                    tls_params=self._tls_params(),
                    keepalive=30,
                ) as client:
                    self._client = client
                    await client.subscribe(TELEMETRY, qos=1)
                    await client.subscribe(EVENTS, qos=1)
                    self._connected.set()
                    delay = 1.0
                    log.info("mqtt connected to %s:%s", s.mqtt_host, s.mqtt_port)
                    async for message in client.messages:
                        await self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("mqtt connection lost (%s); retrying in %.0fs", exc, delay)
            finally:
                self._client = None
                self._connected.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def _handle(self, message: aiomqtt.Message) -> None:
        self.messages_seen += 1
        parsed = parse_topic(str(message.topic))
        if parsed is None:
            return
        hub_id, kind = parsed
        payload = message.payload
        if not isinstance(payload, (bytes, bytearray)):
            return
        try:
            if kind == "telemetry":
                await self.ingestor.ingest_frame(bytes(payload), via_hub=hub_id)
            elif kind == "events":
                await self.ingestor.handle_hub_event(hub_id, bytes(payload))
        except Exception:
            log.exception("failed handling %s message from %s", kind, hub_id)

    # -- publishing
    async def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        await self.wait_connected(5.0)
        assert self._client is not None
        await self._client.publish(topic, payload, qos=qos)

"""Small newline-delimited JSON TCP broadcaster for live PLC state changes."""
import asyncio
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("LIVE_PUBLISHER")


class LiveStatePublisher:
    def __init__(self, host="127.0.0.1", port=55001):
        self.host = host
        self.port = port
        self.clients = set()
        self.snapshot_provider = lambda: []

    async def start(self):
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        log.info("Listening at %s:%s", self.host, self.port)
        return self.server

    @staticmethod
    def _encode(zone, tag, value, kind):
        return (json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "zone": zone,
            "tag": tag,
            "value": bool(value),
        }) + "\n").encode("utf-8")

    async def _handle_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        log.info("Receiver connected: %s", peer)
        try:
            # Snapshot BEFORE registering for change notifications.
            for zone, tag, value in self.snapshot_provider():
                writer.write(self._encode(zone, tag, value, "snapshot"))
            await writer.drain()
            self.clients.add(writer)
            # Detect disconnect without requiring the receiver to send data.
            while await reader.read(1024):
                pass
        except (OSError, ConnectionError) as exc:
            log.warning("Receiver connection ended: %s", exc)
        finally:
            self.clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            log.info("Receiver disconnected: %s", peer)

    async def publish(self, zone, tag, value):
        if not self.clients:
            return
        payload = self._encode(zone, tag, value, "change")
        for writer in tuple(self.clients):
            try:
                writer.write(payload)
                await writer.drain()
            except (OSError, ConnectionError):
                self.clients.discard(writer)

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for writer in tuple(self.clients):
            writer.close()
        self.clients.clear()

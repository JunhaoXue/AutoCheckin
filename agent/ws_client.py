"""Reconnecting WebSocket client for communicating with the cloud server."""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Callable, Optional

import websockets

logger = logging.getLogger("agent.ws")


class WSClient:
    def __init__(self, server_url: str, token: str = ""):
        self.server_url = server_url
        self.token = token
        self.ws = None
        self._running = False
        self._on_command: Optional[Callable] = None
        self._reconnect_delay = 1  # seconds, exponential backoff
        self._max_reconnect_delay = 60

    def on_command(self, handler: Callable):
        """Register a command handler: async def handler(msg: dict)"""
        self._on_command = handler

    async def start(self):
        """Start the WebSocket client with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"WebSocket disconnected: {e}")
                delay = min(
                    self._reconnect_delay * (1 + random.random()),
                    self._max_reconnect_delay
                )
                logger.info(f"Reconnecting in {delay:.1f}s...")
                await asyncio.sleep(delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self.ws:
            await self.ws.close()

    async def _connect_and_listen(self):
        """Connect to server and listen for messages."""
        url = f"{self.server_url}?token={self.token}"
        logger.info(f"Connecting to {self.server_url}...")

        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self.ws = ws
            self._reconnect_delay = 1  # Reset on successful connect
            logger.info("WebSocket connected to server")

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if self._on_command:
                        await self._on_command(msg)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from server: {raw[:200]}")
                except Exception as e:
                    logger.error(f"Error handling command: {e}", exc_info=True)

        self.ws = None

    async def send(self, msg: dict):
        """Send a message to the server."""
        if not self.ws:
            logger.warning("Cannot send: not connected")
            return False
        try:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False

    async def send_heartbeat(self, device_status: dict):
        """Send heartbeat with device status."""
        await self.send({
            "type": "heartbeat",
            "ts": datetime.now().isoformat(),
            "data": device_status,
        })

    async def send_device_status(self, status: dict):
        """Send full device status."""
        await self.send({
            "type": "device_status",
            "ts": datetime.now().isoformat(),
            "data": status,
        })

    async def send_checkin_result(self, result: dict, trigger: str = "scheduled", msg_id: str = None):
        """Send check-in result."""
        msg = {
            "type": "checkin_result",
            "ts": datetime.now().isoformat(),
            "data": {**result, "trigger": trigger},
        }
        if msg_id:
            msg["msg_id"] = msg_id
        await self.send(msg)

    async def send_screenshot(self, b64_data: str, msg_id: str = None):
        """Send screenshot data."""
        msg = {
            "type": "screenshot_result",
            "ts": datetime.now().isoformat(),
            "data": {"screenshot_b64": b64_data},
        }
        if msg_id:
            msg["msg_id"] = msg_id
        await self.send(msg)

    async def send_error(self, error_code: str, message: str, context: str = "", screenshot_b64: str = "", msg_id: str = None):
        """Send error report."""
        msg = {
            "type": "error",
            "ts": datetime.now().isoformat(),
            "data": {
                "error_code": error_code,
                "message": message,
                "context": context,
                "screenshot_b64": screenshot_b64,
            },
        }
        if msg_id:
            msg["msg_id"] = msg_id
        await self.send(msg)

    async def send_log(self, level: str, message: str, logger_name: str = ""):
        """Send a log entry to the server."""
        await self.send({
            "type": "log",
            "ts": datetime.now().isoformat(),
            "data": {
                "level": level,
                "message": message,
                "logger": logger_name,
            },
        })

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.open

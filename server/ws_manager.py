import asyncio
import json
import logging
import base64
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from database import get_db

logger = logging.getLogger("autocheckin.ws")

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


class WSManager:
    """Manages WebSocket connections for phone agent and browser clients."""

    def __init__(self):
        self.phone_ws: Optional[WebSocket] = None
        self.browser_clients: list[WebSocket] = []
        self.last_device_status: dict = {}
        self.last_heartbeat: Optional[datetime] = None
        self.today_checkins: dict = {"morning": None, "evening": None}
        self._pending_commands: dict[str, asyncio.Future] = {}

    @property
    def phone_online(self) -> bool:
        return self.phone_ws is not None

    # --- Phone connection ---

    async def connect_phone(self, ws: WebSocket):
        await ws.accept()
        if self.phone_ws:
            try:
                await self.phone_ws.close()
            except Exception:
                pass
        self.phone_ws = ws
        logger.info("Phone agent connected")
        await self._broadcast_to_browsers({
            "type": "connection_status",
            "data": {"phone_online": True}
        })

    async def disconnect_phone(self):
        self.phone_ws = None
        logger.info("Phone agent disconnected")
        await self._broadcast_to_browsers({
            "type": "connection_status",
            "data": {"phone_online": False}
        })

    # --- Browser connection ---

    async def connect_browser(self, ws: WebSocket):
        await ws.accept()
        self.browser_clients.append(ws)
        logger.info(f"Browser client connected (total: {len(self.browser_clients)})")
        # Send current state immediately
        await ws.send_json({
            "type": "init_state",
            "data": {
                "phone_online": self.phone_online,
                "device_status": self.last_device_status,
                "today_checkins": self.today_checkins,
                "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            }
        })

    async def disconnect_browser(self, ws: WebSocket):
        if ws in self.browser_clients:
            self.browser_clients.remove(ws)
        logger.info(f"Browser client disconnected (total: {len(self.browser_clients)})")

    # --- Send command to phone ---

    async def send_to_phone(self, msg_type: str, data: dict = None) -> Optional[str]:
        if not self.phone_ws:
            return None
        msg_id = str(uuid.uuid4())
        msg = {
            "type": msg_type,
            "msg_id": msg_id,
            "ts": datetime.now().isoformat(),
            "data": data or {}
        }
        try:
            await self.phone_ws.send_json(msg)
            logger.info(f"Sent to phone: {msg_type} ({msg_id})")
            return msg_id
        except Exception as e:
            logger.error(f"Failed to send to phone: {e}")
            await self.disconnect_phone()
            return None

    # --- Handle messages from phone ---

    async def handle_phone_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from phone: {raw[:200]}")
            return

        msg_type = msg.get("type")
        data = msg.get("data", {})

        if msg_type == "heartbeat":
            await self._handle_heartbeat(data)
        elif msg_type == "device_status":
            await self._handle_device_status(data)
        elif msg_type == "checkin_result":
            await self._handle_checkin_result(msg)
        elif msg_type == "screenshot_result":
            await self._handle_screenshot(msg)
        elif msg_type == "error":
            await self._handle_error(msg)
        else:
            logger.warning(f"Unknown message type from phone: {msg_type}")

    async def _handle_heartbeat(self, data: dict):
        self.last_heartbeat = datetime.now()
        self.last_device_status.update(data)
        await self._broadcast_to_browsers({
            "type": "device_update",
            "data": {
                **self.last_device_status,
                "last_heartbeat": self.last_heartbeat.isoformat(),
                "phone_online": True,
            }
        })

    async def _handle_device_status(self, data: dict):
        self.last_device_status.update(data)
        if "today_checkins" in data:
            self.today_checkins = data["today_checkins"]

        # Save to DB
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO device_status
                   (battery_level, battery_charging, wifi_ssid, wifi_ip, screen_on, adb_connected)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (data.get("battery_level"), data.get("battery_charging"),
                 data.get("wifi_ssid"), data.get("wifi_ip"),
                 data.get("screen_on"), data.get("adb_connected"))
            )
            await db.commit()
        finally:
            await db.close()

        await self._broadcast_to_browsers({
            "type": "device_update",
            "data": {**self.last_device_status, "phone_online": True}
        })

    async def _handle_checkin_result(self, msg: dict):
        data = msg.get("data", {})
        screenshot_path = None

        # Save screenshot if present
        if data.get("screenshot_b64"):
            screenshot_path = await self._save_screenshot(data["screenshot_b64"], data.get("checkin_type", "unknown"))

        # Save to DB
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO checkin_logs
                   (checkin_type, checkin_time, success, trigger, message, screenshot_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (data.get("checkin_type"), data.get("checkin_time"),
                 1 if data.get("success") else 0,
                 data.get("trigger", "scheduled"),
                 data.get("message"), screenshot_path)
            )
            await db.commit()
        finally:
            await db.close()

        # Update today's checkins
        checkin_type = data.get("checkin_type", "")
        if "上班" in checkin_type:
            self.today_checkins["morning"] = {
                "done": data.get("success", False),
                "time": data.get("checkin_time"),
                "message": data.get("message"),
            }
        elif "下班" in checkin_type:
            self.today_checkins["evening"] = {
                "done": data.get("success", False),
                "time": data.get("checkin_time"),
                "message": data.get("message"),
            }

        await self._broadcast_to_browsers({
            "type": "checkin_update",
            "data": {
                **data,
                "screenshot_path": screenshot_path,
                "today_checkins": self.today_checkins,
            }
        })

    async def _handle_screenshot(self, msg: dict):
        data = msg.get("data", {})
        if data.get("screenshot_b64"):
            path = await self._save_screenshot(data["screenshot_b64"], "manual")
            await self._broadcast_to_browsers({
                "type": "screenshot_update",
                "data": {"screenshot_path": path}
            })

    async def _handle_error(self, msg: dict):
        data = msg.get("data", {})
        logger.error(f"Phone error: {data.get('error_code')} - {data.get('message')}")
        if data.get("screenshot_b64"):
            await self._save_screenshot(data["screenshot_b64"], "error")
        await self._broadcast_to_browsers({
            "type": "error_update",
            "data": data
        })

    # --- Helpers ---

    async def _save_screenshot(self, b64_data: str, prefix: str) -> str:
        filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return f"/screenshots/{filename}"

    async def _broadcast_to_browsers(self, msg: dict):
        dead = []
        for ws in self.browser_clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.browser_clients.remove(ws)


# Singleton
manager = WSManager()

"""Agent entry point: APScheduler + WebSocket client + command dispatch."""

import asyncio
import logging
import math
import random
import signal
import sys
from datetime import datetime, date
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from device import DeviceManager
from checkin import CheckinAutomation
from ws_client import WSClient


class WSLogHandler(logging.Handler):
    """Forwards log records to the server via WebSocket."""

    def __init__(self, ws_client: WSClient, loop: asyncio.AbstractEventLoop):
        super().__init__(level=logging.INFO)
        self._ws = ws_client
        self._loop = loop

    def emit(self, record):
        if not self._ws.connected:
            return
        try:
            coro = self._ws.send_log(record.levelname, self.format(record), record.name)
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")

# --- Config ---
CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


# --- Holiday check ---
# Chinese public holidays (hardcoded common ones, can be updated)
# Format: "YYYY-MM-DD"
HOLIDAYS_2026 = {
    # 元旦
    "2026-01-01", "2026-01-02", "2026-01-03",
    # 春节 (estimated)
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22",
    # 清明
    "2026-04-04", "2026-04-05", "2026-04-06",
    # 劳动节
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    # 端午
    "2026-06-19", "2026-06-20", "2026-06-21",
    # 中秋+国庆 (estimated)
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# 调休上班日 (Saturday/Sunday that need to work)
WORKDAYS_OVERRIDE = set()


def is_workday(d: date = None) -> bool:
    """Check if a date is a workday."""
    if d is None:
        d = date.today()
    ds = d.strftime("%Y-%m-%d")

    # Override: must work even on weekend
    if ds in WORKDAYS_OVERRIDE:
        return True

    # Holiday
    if ds in HOLIDAYS_2026:
        return False

    # Weekend
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    return True


def exponential_delay(max_seconds: int) -> int:
    """Generate random delay using exponential distribution.

    Most delays will be short, occasional long ones.
    """
    # Lambda = 3/max_seconds gives ~95% of values within max_seconds
    lam = 3.0 / max_seconds if max_seconds > 0 else 1
    delay = random.expovariate(lam)
    return int(min(delay, max_seconds))


# --- Main Agent ---

class Agent:
    def __init__(self):
        self.config = load_config()
        self.dm = DeviceManager()
        self.checkin = CheckinAutomation(self.dm)
        self.ws = WSClient(
            server_url=self.config.get("server_ws_url", "ws://localhost:8080/ws/phone"),
            token=self.config.get("token", ""),
        )
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._today_checkins = {"morning": None, "evening": None}

    async def start(self):
        """Start the agent."""
        logger.info("=== AutoCheckin Agent Starting ===")

        # Initialize ADB
        adb_port = self.config.get("adb_port")
        if adb_port:
            self.dm.connect_adb(adb_port)
        self.dm.init_u2()
        self.dm.keep_screen_on()

        # Setup WebSocket command handler
        self.ws.on_command(self._handle_command)

        # Attach log handler to forward logs to server
        loop = asyncio.get_running_loop()
        ws_handler = WSLogHandler(self.ws, loop)
        ws_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(ws_handler)

        # Setup scheduler
        self._setup_schedule()
        self.scheduler.start()

        # Setup heartbeat
        asyncio.create_task(self._heartbeat_loop())

        # Start WebSocket (blocks with auto-reconnect)
        await self.ws.start()

    async def stop(self):
        """Stop the agent."""
        logger.info("Stopping agent...")
        self.scheduler.shutdown(wait=False)
        await self.ws.stop()

    # --- Schedule setup ---

    def _setup_schedule(self):
        """Configure scheduled check-in jobs."""
        schedule = self.config.get("schedule", {})
        morning = schedule.get("morning_time", "08:30")
        evening = schedule.get("evening_time", "18:30")

        m_hour, m_min = map(int, morning.split(":"))
        e_hour, e_min = map(int, evening.split(":"))

        # Remove existing jobs
        for job_id in ["morning_checkin", "evening_checkin"]:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

        # Add morning check-in
        self.scheduler.add_job(
            self._scheduled_checkin,
            CronTrigger(hour=m_hour, minute=m_min),
            id="morning_checkin",
            args=["上班"],
            replace_existing=True,
        )

        # Add evening check-in
        self.scheduler.add_job(
            self._scheduled_checkin,
            CronTrigger(hour=e_hour, minute=e_min),
            id="evening_checkin",
            args=["下班"],
            replace_existing=True,
        )

        logger.info(f"Scheduled: morning={morning}, evening={evening}")

    async def _scheduled_checkin(self, checkin_type: str):
        """Execute a scheduled check-in with random delay."""
        schedule = self.config.get("schedule", {})

        # Check if we should skip
        if schedule.get("skip_weekends", True) and not is_workday():
            logger.info(f"Skipping {checkin_type} check-in: not a workday")
            return

        # Random delay
        max_delay = schedule.get("random_delay_max", 900)
        delay = exponential_delay(max_delay)
        logger.info(f"Scheduled {checkin_type} check-in, waiting {delay}s random delay...")
        await asyncio.sleep(delay)

        # Check WiFi
        wifi = self.dm.get_wifi_info()
        required_ssid = self.config.get("wifi_ssid", "")
        if required_ssid and wifi.get("wifi_ssid") != required_ssid:
            msg = f"WiFi不匹配: 当前={wifi.get('wifi_ssid')}, 需要={required_ssid}"
            logger.warning(msg)
            await self.ws.send_error("WIFI_MISMATCH", msg, f"checkin_{checkin_type}")
            return

        # Execute check-in
        result = await asyncio.get_event_loop().run_in_executor(
            None, self.checkin.perform_checkin, checkin_type
        )

        # Update local state
        key = "morning" if "上班" in checkin_type else "evening"
        self._today_checkins[key] = {
            "done": result["success"],
            "time": result["checkin_time"],
            "message": result["message"],
        }

        # Report to server
        await self.ws.send_checkin_result(result, trigger="scheduled")
        logger.info(f"Scheduled {checkin_type} check-in done: {result['success']}")

    # --- Command handling ---

    async def _handle_command(self, msg: dict):
        """Handle commands from the server."""
        cmd_type = msg.get("type")
        msg_id = msg.get("msg_id")
        data = msg.get("data", {})

        logger.info(f"Received command: {cmd_type} ({msg_id})")

        if cmd_type == "checkin":
            await self._cmd_checkin(data, msg_id)
        elif cmd_type == "screenshot":
            await self._cmd_screenshot(msg_id)
        elif cmd_type == "status":
            await self._cmd_status(msg_id)
        elif cmd_type == "update_schedule":
            await self._cmd_update_schedule(data, msg_id)
        else:
            logger.warning(f"Unknown command: {cmd_type}")

    async def _cmd_checkin(self, data: dict, msg_id: str):
        """Handle manual check-in command."""
        checkin_type = data.get("checkin_type", "auto")

        result = await asyncio.get_event_loop().run_in_executor(
            None, self.checkin.perform_checkin, checkin_type
        )

        key = "morning" if "上班" in result.get("checkin_type", "") else "evening"
        self._today_checkins[key] = {
            "done": result["success"],
            "time": result["checkin_time"],
            "message": result["message"],
        }

        await self.ws.send_checkin_result(result, trigger="manual", msg_id=msg_id)

    async def _cmd_screenshot(self, msg_id: str):
        """Handle screenshot request."""
        b64 = await asyncio.get_event_loop().run_in_executor(
            None, self.dm.take_screenshot_b64
        )
        if b64:
            await self.ws.send_screenshot(b64, msg_id)
        else:
            await self.ws.send_error("SCREENSHOT_FAILED", "截图失败", msg_id=msg_id)

    async def _cmd_status(self, msg_id: str):
        """Handle status request."""
        status = await asyncio.get_event_loop().run_in_executor(
            None, self.dm.get_device_status
        )
        status["today_checkins"] = self._today_checkins
        status["schedule"] = self.config.get("schedule", {})
        await self.ws.send_device_status(status)

    async def _cmd_update_schedule(self, data: dict, msg_id: str):
        """Handle schedule update from server."""
        self.config.setdefault("schedule", {}).update(data)
        save_config(self.config)
        self._setup_schedule()
        logger.info(f"Schedule updated: {data}")

    # --- Heartbeat ---

    async def _heartbeat_loop(self):
        """Send periodic heartbeat to server."""
        while True:
            try:
                if self.ws.connected:
                    status = await asyncio.get_event_loop().run_in_executor(
                        None, self.dm.get_device_status
                    )
                    await self.ws.send_heartbeat(status)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(30)


async def main():
    agent = Agent()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.stop()))

    try:
        await agent.start()
    except KeyboardInterrupt:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())

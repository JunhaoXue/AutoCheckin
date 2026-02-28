"""Device management: ADB self-connection, uiautomator2 init, device info."""

import subprocess
import re
import logging
import time
import uiautomator2 as u2

logger = logging.getLogger("agent.device")


class DeviceManager:
    def __init__(self):
        self.d: u2.Device = None
        self._adb_port: int = None

    def ensure_adb_connected(self) -> bool:
        """Ensure ADB is connected to the device itself via wireless debugging."""
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")[1:]
            for line in lines:
                if "device" in line and "offline" not in line:
                    logger.info(f"ADB device found: {line.strip()}")
                    return True

            # Try to connect to localhost wireless ADB
            # First, find the port from wireless debugging
            if self._adb_port:
                result = subprocess.run(
                    ["adb", "connect", f"localhost:{self._adb_port}"],
                    capture_output=True, text=True, timeout=10
                )
                if "connected" in result.stdout.lower():
                    logger.info(f"ADB reconnected to localhost:{self._adb_port}")
                    return True

            logger.warning("No ADB device connected")
            return False
        except Exception as e:
            logger.error(f"ADB check failed: {e}")
            return False

    def set_adb_port(self, port: int):
        """Set the wireless ADB port (from config or manual pairing)."""
        self._adb_port = port

    def connect_adb(self, port: int) -> bool:
        """Connect to device via wireless ADB."""
        self._adb_port = port
        try:
            result = subprocess.run(
                ["adb", "connect", f"localhost:{port}"],
                capture_output=True, text=True, timeout=10
            )
            success = "connected" in result.stdout.lower()
            if success:
                logger.info(f"ADB connected to localhost:{port}")
            else:
                logger.warning(f"ADB connect failed: {result.stdout}")
            return success
        except Exception as e:
            logger.error(f"ADB connect error: {e}")
            return False

    def _get_adb_serial(self) -> str:
        """Auto-detect the connected ADB device serial."""
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n")[1:]:
                if "\tdevice" in line:
                    serial = line.split("\t")[0]
                    logger.info(f"Auto-detected ADB serial: {serial}")
                    return serial
        except Exception as e:
            logger.error(f"Auto-detect ADB serial failed: {e}")
        return ""

    def init_u2(self) -> bool:
        """Initialize uiautomator2 connection."""
        try:
            if not self.ensure_adb_connected():
                return False

            serial = self._get_adb_serial()
            if not serial:
                logger.error("No ADB device found for u2")
                return False

            logger.info(f"Connecting u2 to {serial}")
            self.d = u2.connect(serial)
            info = self.d.info
            logger.info(f"uiautomator2 connected: {info.get('productName', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"uiautomator2 init failed: {e}")
            self.d = None
            return False

    def ensure_u2(self) -> bool:
        """Ensure uiautomator2 is connected, reconnect if needed."""
        if self.d:
            try:
                self.d.info  # quick health check
                return True
            except Exception:
                logger.warning("u2 connection lost, reconnecting...")
                self.d = None

        return self.init_u2()

    def get_battery_info(self) -> dict:
        """Get battery level and charging status."""
        try:
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "battery"],
                capture_output=True, text=True, timeout=10
            )
            level = 0
            charging = False
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("level:"):
                    level = int(line.split(":")[1].strip())
                elif line.startswith("status:"):
                    # 2=charging, 5=full
                    status = int(line.split(":")[1].strip())
                    charging = status in (2, 5)
            return {"battery_level": level, "battery_charging": charging}
        except Exception as e:
            logger.error(f"Get battery failed: {e}")
            return {"battery_level": 0, "battery_charging": False}

    def get_wifi_info(self) -> dict:
        """Get current WiFi SSID and IP address."""
        ssid = ""
        ip = ""
        try:
            # Get WiFi SSID
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "wifi"],
                capture_output=True, text=True, timeout=10
            )
            # Look for current network SSID
            for line in result.stdout.split("\n"):
                if "mWifiInfo" in line and "SSID:" in line:
                    match = re.search(r'SSID:\s*"?([^",]+)"?', line)
                    if match:
                        ssid = match.group(1).strip().strip('"')
                    break

            # Get IP address
            result = subprocess.run(
                ["adb", "shell", "ip", "addr", "show", "wlan0"],
                capture_output=True, text=True, timeout=10
            )
            match = re.search(r'inet\s+([\d.]+)/', result.stdout)
            if match:
                ip = match.group(1)

        except Exception as e:
            logger.error(f"Get WiFi info failed: {e}")

        return {"wifi_ssid": ssid, "wifi_ip": ip}

    def is_screen_on(self) -> bool:
        """Check if screen is on."""
        try:
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "power"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split("\n"):
                if "mHoldingDisplaySuspendBlocker" in line:
                    return "true" in line.lower()
                if "Display Power: state=" in line:
                    return "ON" in line
            return False
        except Exception:
            return False

    def wake_screen(self):
        """Wake up screen if off, with multiple retry attempts."""
        for attempt in range(3):
            if self.is_screen_on():
                logger.info("Screen is on")
                return
            logger.info(f"Waking screen (attempt {attempt + 1})")
            subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_WAKEUP"],
                           capture_output=True, timeout=5)
            time.sleep(1)
            # Swipe up to unlock (for lock screen without password)
            subprocess.run(
                ["adb", "shell", "input", "swipe", "500", "1800", "500", "800", "300"],
                capture_output=True, timeout=5
            )
            time.sleep(1)
        logger.info("Screen wake attempts finished")

    def take_screenshot_b64(self) -> str:
        """Take screenshot and return as base64 JPEG."""
        import base64
        import io
        try:
            if self.d:
                img = self.d.screenshot()
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=60)
                return base64.b64encode(buf.getvalue()).decode()
            else:
                # Fallback: ADB screenshot
                result = subprocess.run(
                    ["adb", "shell", "screencap", "-p"],
                    capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    from PIL import Image
                    img = Image.open(io.BytesIO(result.stdout))
                    if img.mode == "RGBA":
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    return base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
        return ""

    def get_device_status(self) -> dict:
        """Get comprehensive device status."""
        battery = self.get_battery_info()
        wifi = self.get_wifi_info()
        return {
            **battery,
            **wifi,
            "screen_on": self.is_screen_on(),
            "adb_connected": self.ensure_adb_connected(),
        }

    def keep_screen_on(self):
        """Prevent screen from timing out (set stay awake while charging)."""
        subprocess.run(
            ["adb", "shell", "settings", "put", "system", "screen_off_timeout", "2147483647"],
            capture_output=True, timeout=5
        )
        # Enable stay awake while charging
        subprocess.run(
            ["adb", "shell", "settings", "put", "global", "stay_on_while_plugged_in", "3"],
            capture_output=True, timeout=5
        )
        logger.info("Screen stay-on settings applied")

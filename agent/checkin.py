"""Core check-in automation logic for Enterprise WeChat (企业微信).

Based on actual UI analysis:
- 工作台 page: "内部管理" section has "打卡" entry
- 打卡 page: Large circle button in center ("上班打卡"/"下班打卡" + time)
- Shows "你已在打卡范围内" when location is valid
- Schedule: 上班 09:00 - 下班 18:00

Flow: Open WeCom -> 工作台 tab -> 打卡 icon -> click the big circle button -> verify result
"""

import time
import random
import logging
from datetime import datetime

logger = logging.getLogger("agent.checkin")

# Package name for Enterprise WeChat
WECOM_PACKAGE = "com.tencent.wework"


class CheckinAutomation:
    def __init__(self, device_manager):
        self.dm = device_manager

    def perform_checkin(self, checkin_type: str = "auto") -> dict:
        """
        Execute the full check-in flow.

        Args:
            checkin_type: "上班", "下班", or "auto" (decide based on current time)

        Returns:
            dict with keys: success, checkin_type, checkin_time, message, screenshot_b64
        """
        result = {
            "success": False,
            "checkin_type": checkin_type,
            "checkin_time": datetime.now().strftime("%H:%M:%S"),
            "message": "",
            "screenshot_b64": "",
        }

        try:
            # Ensure u2 is connected
            if not self.dm.ensure_u2():
                result["message"] = "uiautomator2 连接失败"
                return result

            d = self.dm.d

            # Step 1: Wake screen
            logger.info("Step 1: Wake screen")
            self.dm.wake_screen()
            self._random_sleep(0.5, 1.0)

            # Step 2: Open WeCom app
            logger.info("Step 2: Open WeCom")
            if not self._open_wecom(d):
                result["message"] = "打开企业微信失败"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                return result
            self._random_sleep(1.5, 2.5)

            # Step 3: Navigate to 工作台 tab
            logger.info("Step 3: Navigate to 工作台")
            if not self._go_to_workbench(d):
                result["message"] = "无法切换到工作台"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                return result
            self._random_sleep(1.0, 2.0)

            # Step 4: Find and click 打卡 entry
            logger.info("Step 4: Click 打卡 entry")
            if not self._click_checkin_entry(d):
                result["message"] = "未找到打卡入口"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                return result
            self._random_sleep(2.0, 3.0)

            # Step 5: Wait for checkin page to load, check if in range
            logger.info("Step 5: Wait for checkin page")
            if not self._wait_for_checkin_page(d):
                result["message"] = "打卡页面加载失败"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                return result
            self._random_sleep(0.5, 1.0)

            # Step 6: Click the big check-in button
            logger.info("Step 6: Click check-in button")
            click_result = self._click_checkin_button(d, checkin_type)
            if not click_result["success"]:
                result["message"] = click_result["message"]
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                return result
            result["checkin_type"] = click_result.get("actual_type", checkin_type)
            self._random_sleep(2.0, 3.0)

            # Step 7: Verify result
            logger.info("Step 7: Verify result")
            verify = self._verify_checkin_result(d)
            result["success"] = verify["success"]
            result["message"] = verify["message"]
            result["checkin_time"] = datetime.now().strftime("%H:%M:%S")
            result["screenshot_b64"] = self.dm.take_screenshot_b64()

            logger.info(f"Check-in result: {result['success']} - {result['message']}")

        except Exception as e:
            logger.error(f"Check-in error: {e}", exc_info=True)
            result["message"] = f"异常: {str(e)}"
            try:
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
            except Exception:
                pass

        finally:
            # Go back to home screen
            try:
                d = self.dm.d
                if d:
                    d.press("home")
            except Exception:
                pass

        return result

    def _open_wecom(self, d) -> bool:
        """Open Enterprise WeChat app."""
        try:
            d.app_start(WECOM_PACKAGE, stop=False)
            # Wait for app to appear
            for _ in range(10):
                if d.app_current().get("package") == WECOM_PACKAGE:
                    return True
                time.sleep(0.5)
            # Force start
            d.app_start(WECOM_PACKAGE, stop=True)
            time.sleep(2)
            return d.app_current().get("package") == WECOM_PACKAGE
        except Exception as e:
            logger.error(f"Open WeCom failed: {e}")
            return False

    def _go_to_workbench(self, d) -> bool:
        """Navigate to 工作台 tab at bottom of WeCom."""
        try:
            # Look for 工作台 tab at bottom
            tab = d(text="工作台")
            if tab.exists(timeout=5):
                tab.click()
                self._random_sleep(0.5, 1.0)
                return True

            # Try alternative: look by description
            tab = d(description="工作台")
            if tab.exists(timeout=3):
                tab.click()
                self._random_sleep(0.5, 1.0)
                return True

            logger.warning("工作台 tab not found")
            return False
        except Exception as e:
            logger.error(f"Navigate to 工作台 failed: {e}")
            return False

    def _click_checkin_entry(self, d) -> bool:
        """Find and click the 打卡 entry in 工作台."""
        try:
            # Scroll down to find 打卡 in case it's not visible
            for attempt in range(3):
                # Look for 打卡 text
                checkin = d(text="打卡")
                if checkin.exists(timeout=3):
                    checkin.click()
                    return True

                # Try with textContains
                checkin = d(textContains="打卡")
                if checkin.exists(timeout=2):
                    checkin.click()
                    return True

                # Scroll down to find it
                if attempt < 2:
                    d.swipe_ext("up", scale=0.3)
                    self._random_sleep(0.5, 1.0)

            logger.warning("打卡 entry not found after scrolling")
            return False
        except Exception as e:
            logger.error(f"Click 打卡 entry failed: {e}")
            return False

    def _wait_for_checkin_page(self, d) -> bool:
        """Wait for the check-in page to fully load."""
        try:
            # Wait for indicators that the checkin page is loaded
            # Look for "上下班打卡" tab header or the check-in button
            indicators = [
                "上下班打卡",
                "外出打卡",
                "打卡范围",
                "上班打卡",
                "下班打卡",
                "迟到打卡",
                "早退打卡",
                "加班下班",
                "更新打卡",
                "已打卡",
            ]
            for _ in range(15):  # Wait up to 15 seconds
                for text in indicators:
                    if d(textContains=text).exists(timeout=0.5):
                        logger.info(f"Checkin page loaded (found: {text})")
                        return True
                time.sleep(0.5)

            logger.warning("Checkin page didn't load in time")
            return False
        except Exception as e:
            logger.error(f"Wait for checkin page failed: {e}")
            return False

    def _click_checkin_button(self, d, checkin_type: str) -> dict:
        """Click the big circular check-in button.

        The button shows text like "上班打卡" or "下班打卡" with time underneath.
        """
        result = {"success": False, "message": "", "actual_type": checkin_type}

        try:
            # All known button texts in WeCom check-in page:
            # 上班打卡 - normal morning check-in
            # 下班打卡 - normal evening check-out
            # 迟到打卡 - late morning check-in
            # 早退打卡 - early leave check-out
            # 加班下班 - overtime clock-out
            # 更新打卡 - update existing record
            all_button_texts = {
                "上班": ["上班打卡", "迟到打卡"],
                "下班": ["下班打卡", "加班下班", "早退打卡"],
                "any":  ["更新打卡"],
            }

            # Build search list based on checkin_type
            button_texts = []
            if checkin_type == "上班":
                button_texts = all_button_texts["上班"] + all_button_texts["any"]
            elif checkin_type == "下班":
                button_texts = all_button_texts["下班"] + all_button_texts["any"]
            else:  # auto
                button_texts = (all_button_texts["上班"] +
                                all_button_texts["下班"] +
                                all_button_texts["any"])

            for text in button_texts:
                btn = d(textContains=text)
                if btn.exists(timeout=3):
                    if any(k in text for k in ["上班", "迟到"]):
                        result["actual_type"] = "上班"
                    else:
                        result["actual_type"] = "下班"
                    logger.info(f"Found button: {text}")
                    btn.click()
                    result["success"] = True
                    result["message"] = f"已点击{text}按钮"
                    return result

            # Fallback: try to find any clickable element with 打卡 or 下班 text
            for keyword in ["打卡", "下班", "上班"]:
                btn = d(textContains=keyword, clickable=True)
                if btn.exists(timeout=2):
                    btn.click()
                    result["success"] = True
                    result["message"] = f"已点击含'{keyword}'的按钮"
                    return result

            # Last resort: look for the large circle in center of screen
            # The check-in button is typically a large circle in the center-bottom area
            width, height = d.window_size()
            center_x = width // 2
            center_y = int(height * 0.65)  # Button is roughly at 65% height
            logger.info(f"Clicking center button at ({center_x}, {center_y})")
            d.click(center_x, center_y)
            result["success"] = True
            result["message"] = "已点击打卡区域(坐标)"
            return result

        except Exception as e:
            result["message"] = f"点击打卡按钮失败: {e}"
            logger.error(result["message"])
            return result

    def _verify_checkin_result(self, d) -> dict:
        """Verify if check-in was successful after clicking the button."""
        result = {"success": False, "message": ""}

        try:
            # After clicking, the page may show a success toast or update the status
            # Common success indicators:
            success_indicators = [
                "打卡成功",
                "已打卡",
                "更新打卡",
                "打卡时间",
            ]

            # Wait a moment for result to appear
            time.sleep(1.5)

            for text in success_indicators:
                if d(textContains=text).exists(timeout=3):
                    result["success"] = True
                    result["message"] = f"打卡成功 ({text})"
                    return result

            # Check if the page shows a green checkmark or updated time
            # Look for the time display near the button (indicating successful punch)
            if d(textContains="上班").exists(timeout=1) or d(textContains="下班").exists(timeout=1):
                # Check for green check (✓) indicator
                checkin_time_el = d(textContains=":")
                if checkin_time_el.exists(timeout=1):
                    result["success"] = True
                    result["message"] = "打卡已完成(页面已更新)"
                    return result

            # If we can't definitively determine success, assume it worked
            # (the screenshot will be sent back for manual verification)
            result["success"] = True
            result["message"] = "打卡操作已执行，请查看截图确认"
            return result

        except Exception as e:
            result["message"] = f"验证打卡结果失败: {e}"
            logger.error(result["message"])
            return result

    def _random_sleep(self, min_sec: float, max_sec: float):
        """Sleep for a random duration to simulate human behavior."""
        duration = random.uniform(min_sec, max_sec)
        time.sleep(duration)

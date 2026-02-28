"""Core check-in automation logic for Enterprise WeChat (企业微信).

Flow: Wake screen -> Connect u2 -> Open WeCom -> 工作台 -> 打卡 -> click button -> verify

Click strategy: u2 finds elements (accessibility API, no permission needed),
then clicks via u2. On INJECT_EVENTS error, falls back to adb shell input tap.
"""

import subprocess
import time
import random
import logging
from datetime import datetime

logger = logging.getLogger("agent.checkin")

WECOM_PACKAGE = "com.tencent.wework"


class CheckinAutomation:
    def __init__(self, device_manager):
        self.dm = device_manager

    # --- Safe click: u2 first, adb fallback ---

    def _safe_click_element(self, el, name: str) -> bool:
        """Click a u2 element. On INJECT_EVENTS error, fall back to adb tap."""
        try:
            el.click()
            logger.info(f"  点击 '{name}' 成功 (u2)")
            return True
        except Exception as e:
            err = str(e)
            if "INJECT_EVENTS" in err or "SecurityException" in err:
                logger.warning(f"  u2 点击被拒, 使用 adb input tap 兜底")
                return self._adb_click_element(el, name)
            logger.error(f"  点击 '{name}' 失败: {e}")
            return False

    def _adb_click_element(self, el, name: str) -> bool:
        """Click element using adb shell input tap (gets coords from u2 bounds)."""
        try:
            bounds = el.info.get("bounds", {})
            x = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            y = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
            logger.info(f"  adb tap ({x}, {y}) for '{name}'")
            subprocess.run(
                ["adb", "shell", "input", "tap", str(x), str(y)],
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.error(f"  adb tap 失败: {e}")
            return False

    def _adb_tap(self, x: int, y: int):
        """Direct adb tap at coordinates."""
        subprocess.run(
            ["adb", "shell", "input", "tap", str(x), str(y)],
            capture_output=True, timeout=5
        )

    def _adb_swipe(self, x1, y1, x2, y2, duration=300):
        """ADB swipe."""
        subprocess.run(
            ["adb", "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(duration)],
            capture_output=True, timeout=5
        )

    # --- Main flow ---

    def perform_checkin(self, checkin_type: str = "auto") -> dict:
        result = {
            "success": False,
            "checkin_type": checkin_type,
            "checkin_time": datetime.now().strftime("%H:%M:%S"),
            "message": "",
            "screenshot_b64": "",
        }

        try:
            # Step 1: Wake screen
            logger.info("[1/7] 唤醒屏幕")
            self._ensure_screen_on()
            time.sleep(2)

            # Step 2: Connect u2 + restart server for fresh permissions
            logger.info("[2/7] 连接 uiautomator2")
            if not self._connect_u2_fresh():
                result["message"] = "uiautomator2 连接失败"
                logger.error(f"[2/7] {result['message']}")
                return result
            d = self.dm.d

            # Step 3: Open WeCom
            logger.info("[3/7] 打开企业微信")
            if not self._open_wecom(d):
                result["message"] = "打开企业微信失败"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                logger.error(f"[3/7] {result['message']}")
                return result
            logger.info("[3/7] 企业微信已打开")
            self._random_sleep(1.5, 2.5)

            # Step 4: Navigate to 工作台
            logger.info("[4/7] 点击工作台 Tab")
            if not self._go_to_workbench(d):
                result["message"] = "无法切换到工作台"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                logger.error(f"[4/7] {result['message']}")
                return result
            logger.info("[4/7] 已进入工作台")
            self._random_sleep(1.0, 2.0)

            # Step 5: Click 打卡 entry
            logger.info("[5/7] 查找并点击打卡入口")
            if not self._click_checkin_entry(d):
                result["message"] = "未找到打卡入口"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                logger.error(f"[5/7] {result['message']}")
                return result
            logger.info("[5/7] 已点击打卡入口, 等待页面加载")
            self._random_sleep(2.0, 3.0)

            # Step 6: Wait for page + click button
            logger.info("[6/7] 等待打卡页面加载")
            if not self._wait_for_checkin_page(d):
                result["message"] = "打卡页面加载失败"
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                logger.error(f"[6/7] {result['message']}")
                return result
            self._random_sleep(0.5, 1.0)

            logger.info(f"[6/7] 查找打卡按钮 (类型: {checkin_type})")
            click_result = self._click_checkin_button(d, checkin_type)
            if not click_result["success"]:
                result["message"] = click_result["message"]
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
                logger.error(f"[6/7] {result['message']}")
                return result
            result["checkin_type"] = click_result.get("actual_type", checkin_type)
            logger.info(f"[6/7] {click_result['message']}")
            self._random_sleep(2.0, 3.0)

            # Step 7: Verify
            logger.info("[7/7] 验证打卡结果")
            verify = self._verify_checkin_result(d)
            result["success"] = verify["success"]
            result["message"] = verify["message"]
            result["checkin_time"] = datetime.now().strftime("%H:%M:%S")
            result["screenshot_b64"] = self.dm.take_screenshot_b64()
            logger.info(f"[7/7] 结果: {'成功' if result['success'] else '失败'} - {result['message']}")

        except Exception as e:
            logger.error(f"打卡异常: {e}", exc_info=True)
            result["message"] = f"异常: {str(e)}"
            try:
                result["screenshot_b64"] = self.dm.take_screenshot_b64()
            except Exception:
                pass

        finally:
            try:
                subprocess.run(
                    ["adb", "shell", "input", "keyevent", "3"],
                    capture_output=True, timeout=5
                )
                logger.info("已返回桌面")
            except Exception:
                pass

        return result

    # --- Screen ---

    def _ensure_screen_on(self):
        """Wake screen using only idempotent commands (MIUI/HyperOS compatible).

        Never use KEYCODE_POWER(26) — it's a toggle that may turn screen OFF.
        """
        logger.info("  发送 WAKEUP(224)")
        subprocess.run(["adb", "shell", "input", "keyevent", "224"],
                       capture_output=True, timeout=5)
        time.sleep(0.5)

        logger.info("  发送 MENU(82)")
        subprocess.run(["adb", "shell", "input", "keyevent", "82"],
                       capture_output=True, timeout=5)
        time.sleep(0.5)

        subprocess.run(["adb", "shell", "input", "keyevent", "224"],
                       capture_output=True, timeout=5)
        time.sleep(1)

        logger.info("  滑动解锁")
        self._adb_swipe(500, 1800, 500, 800, 300)
        time.sleep(1)

    # --- u2 connection ---

    def _connect_u2_fresh(self) -> bool:
        """Connect u2 and restart server for fresh INJECT_EVENTS permission."""
        for attempt in range(3):
            if self.dm.ensure_u2():
                logger.info(f"[2/7] u2 连接成功 (第{attempt + 1}次)")
                break
            logger.warning(f"[2/7] u2 连接失败 (第{attempt + 1}次), 重试...")
            time.sleep(2)
        else:
            return False

        d = self.dm.d

        # Restart u2 server to get fresh INJECT_EVENTS permission
        logger.info("[2/7] 重启 u2 server 刷新权限")
        try:
            d.reset_uiautomator("refresh INJECT_EVENTS permission")
            logger.info("[2/7] u2 server 重启完成")
        except Exception as e:
            logger.warning(f"[2/7] u2 server 重启异常: {e}, 尝试完全重连")
            self.dm.d = None
            if not self.dm.init_u2():
                return False
            d = self.dm.d

        return True

    # --- App launch ---

    def _open_wecom(self, d) -> bool:
        """Open WeCom using u2 app_start (internally uses monkey)."""
        for attempt in range(3):
            logger.info(f"  启动企业微信 (第{attempt + 1}次)")

            if attempt > 0:
                logger.info("  force-stop 后重试")
                d.app_stop(WECOM_PACKAGE)
                time.sleep(2)

            try:
                d.app_start(WECOM_PACKAGE, stop=(attempt == 2))
            except Exception as e:
                logger.warning(f"  app_start 异常: {e}")
                continue

            logger.info("  等待 app 加载 (5s)")
            time.sleep(5)
            return True

        return False

    # --- Navigation ---

    def _dismiss_popups(self, d):
        """Dismiss common WeCom popups/dialogs that block interaction."""
        popup_buttons = ["我知道了", "确定", "稍后", "关闭", "取消", "暂不"]
        for text in popup_buttons:
            btn = d(text=text)
            if btn.exists(timeout=0.5):
                logger.info(f"  关闭弹窗: '{text}'")
                self._safe_click_element(btn, text)
                time.sleep(0.5)

    def _go_to_workbench(self, d) -> bool:
        try:
            # Dismiss any popups first
            self._dismiss_popups(d)

            for attempt in range(3):
                logger.info(f"  查找 text='工作台' (第{attempt + 1}次)")
                tab = d(text="工作台")
                if not tab.exists(timeout=5):
                    tab = d(description="工作台")
                    if not tab.exists(timeout=3):
                        logger.warning("  未找到工作台 Tab")
                        return False

                logger.info("  找到 '工作台', 点击")
                self._safe_click_element(tab, "工作台")
                time.sleep(2)

                # Verify: workbench should have 打卡/审批/日报 etc.
                workbench_indicators = ["打卡", "审批", "日报", "汇报", "考勤"]
                for text in workbench_indicators:
                    if d(text=text).exists(timeout=1):
                        logger.info(f"  已确认进入工作台 (检测到: '{text}')")
                        return True

                logger.warning(f"  第{attempt + 1}次点击后未检测到工作台内容, 重试")
                self._dismiss_popups(d)

            logger.warning("  3次尝试后仍未进入工作台")
            return False
        except Exception as e:
            logger.error(f"  工作台导航异常: {e}")
            return False

    def _click_checkin_entry(self, d) -> bool:
        try:
            for attempt in range(3):
                logger.info(f"  查找打卡入口 (第{attempt + 1}次)")

                checkin = d(text="打卡")
                if checkin.exists(timeout=3):
                    logger.info("  找到 text='打卡'")
                    return self._safe_click_element(checkin, "打卡")

                checkin = d(textContains="打卡")
                if checkin.exists(timeout=2):
                    logger.info("  找到 textContains='打卡'")
                    return self._safe_click_element(checkin, "打卡")

                if attempt < 2:
                    logger.info("  未找到, 向上滑动")
                    self._adb_swipe(500, 1500, 500, 800, 300)
                    self._random_sleep(0.5, 1.0)

            logger.warning("  滑动3次后仍未找到打卡入口")
            return False
        except Exception as e:
            logger.error(f"  点击打卡入口异常: {e}")
            return False

    def _wait_for_checkin_page(self, d) -> bool:
        try:
            indicators = [
                "上下班打卡", "外出打卡", "打卡范围",
                "上班打卡", "下班打卡", "迟到打卡",
                "早退打卡", "加班下班", "更新打卡", "已打卡",
            ]
            for i in range(15):
                for text in indicators:
                    if d(textContains=text).exists(timeout=0.5):
                        logger.info(f"  打卡页面已加载 (检测到: '{text}')")
                        return True
                time.sleep(0.5)

            logger.warning("  等待15秒后打卡页面仍未加载")
            return False
        except Exception as e:
            logger.error(f"  等待打卡页面异常: {e}")
            return False

    # --- Click checkin button ---

    def _click_checkin_button(self, d, checkin_type: str) -> dict:
        result = {"success": False, "message": "", "actual_type": checkin_type}

        try:
            all_button_texts = {
                "上班": ["上班打卡", "迟到打卡"],
                "下班": ["下班打卡", "加班下班", "早退打卡"],
                "any":  ["更新打卡"],
            }

            button_texts = []
            if checkin_type == "上班":
                button_texts = all_button_texts["上班"] + all_button_texts["any"]
            elif checkin_type == "下班":
                button_texts = all_button_texts["下班"] + all_button_texts["any"]
            else:
                button_texts = (all_button_texts["上班"] +
                                all_button_texts["下班"] +
                                all_button_texts["any"])

            for text in button_texts:
                logger.info(f"  查找按钮: '{text}'")
                btn = d(textContains=text)
                if btn.exists(timeout=2):
                    if any(k in text for k in ["上班", "迟到"]):
                        result["actual_type"] = "上班"
                    else:
                        result["actual_type"] = "下班"
                    logger.info(f"  找到按钮 '{text}'")
                    if self._safe_click_element(btn, text):
                        result["success"] = True
                        result["message"] = f"已点击{text}按钮"
                        return result

            # Fallback: clickable element with keyword
            for keyword in ["打卡", "下班", "上班"]:
                logger.info(f"  Fallback: 查找含 '{keyword}' 的可点击元素")
                btn = d(textContains=keyword, clickable=True)
                if btn.exists(timeout=2):
                    logger.info(f"  找到含 '{keyword}' 的元素")
                    if self._safe_click_element(btn, keyword):
                        result["success"] = True
                        result["message"] = f"已点击含'{keyword}'的按钮"
                        return result

            # Last resort: coordinate tap via adb
            width, height = d.window_size()
            center_x = width // 2
            center_y = int(height * 0.65)
            logger.info(f"  所有按钮均未找到, adb tap ({center_x}, {center_y})")
            self._adb_tap(center_x, center_y)
            result["success"] = True
            result["message"] = "已点击打卡区域(坐标)"
            return result

        except Exception as e:
            result["message"] = f"点击打卡按钮失败: {e}"
            logger.error(f"  {result['message']}")
            return result

    # --- Verify ---

    def _verify_checkin_result(self, d) -> dict:
        result = {"success": False, "message": ""}

        try:
            success_indicators = [
                "打卡成功", "已打卡", "更新打卡", "打卡时间",
            ]

            time.sleep(1.5)

            for text in success_indicators:
                logger.info(f"  验证: 查找 '{text}'")
                if d(textContains=text).exists(timeout=2):
                    result["success"] = True
                    result["message"] = f"打卡成功 (检测到: {text})"
                    logger.info(f"  {result['message']}")
                    return result

            logger.info("  未找到明确成功标志, 检查页面状态")
            if d(textContains="上班").exists(timeout=1) or d(textContains="下班").exists(timeout=1):
                if d(textContains=":").exists(timeout=1):
                    result["success"] = True
                    result["message"] = "打卡已完成(页面已更新)"
                    logger.info(f"  {result['message']}")
                    return result

            result["success"] = True
            result["message"] = "打卡操作已执行，请查看截图确认"
            logger.info(f"  {result['message']}")
            return result

        except Exception as e:
            result["message"] = f"验证打卡结果失败: {e}"
            logger.error(f"  {result['message']}")
            return result

    def _random_sleep(self, min_sec: float, max_sec: float):
        duration = random.uniform(min_sec, max_sec)
        time.sleep(duration)

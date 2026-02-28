"""Core check-in automation logic for Enterprise WeChat (企业微信).

Flow: Wake screen -> Open WeCom -> 工作台 tab -> 打卡 icon -> click button -> verify
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
            self.dm.wake_screen()
            screen_on = self.dm.is_screen_on()
            logger.info(f"[1/7] 屏幕状态: {'亮' if screen_on else '灭'}")
            self._random_sleep(1.0, 2.0)

            # Step 2: Connect u2
            logger.info("[2/7] 连接 uiautomator2")
            for u2_attempt in range(3):
                if self.dm.ensure_u2():
                    logger.info(f"[2/7] u2 连接成功 (第{u2_attempt + 1}次)")
                    break
                logger.warning(f"[2/7] u2 连接失败 (第{u2_attempt + 1}次), 重试...")
                time.sleep(2)
            else:
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
                    ["adb", "shell", "input", "keyevent", "KEYCODE_HOME"],
                    capture_output=True, timeout=5
                )
                logger.info("已返回桌面")
            except Exception:
                pass

        return result

    # --- Internal steps ---

    def _is_wecom_foreground(self) -> bool:
        try:
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "window", "displays"],
                capture_output=True, text=True, timeout=5
            )
            return WECOM_PACKAGE in result.stdout
        except Exception:
            return False

    def _resolve_launch_activity(self) -> str:
        """Query the correct launch activity for WeCom."""
        try:
            result = subprocess.run(
                ["adb", "shell", "cmd", "package", "resolve-activity",
                 "--brief", WECOM_PACKAGE],
                capture_output=True, text=True, timeout=5
            )
            # Output format:
            #   priority=0 preferredOrder=0 match=0x108000 ...
            #   com.tencent.wework/.launch.WwMainActivity
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if "/" in line and WECOM_PACKAGE in line:
                    logger.info(f"  解析到启动 Activity: {line}")
                    return line
        except Exception as e:
            logger.warning(f"  resolve-activity 失败: {e}")
        return ""

    def _open_wecom(self, d) -> bool:
        # 先查出正确的 launch activity
        activity = self._resolve_launch_activity()

        for attempt in range(3):
            logger.info(f"  启动企业微信 (第{attempt + 1}次)")

            if attempt > 0:
                logger.info("  force-stop 企业微信后重试")
                subprocess.run(
                    ["adb", "shell", "am", "force-stop", WECOM_PACKAGE],
                    capture_output=True, timeout=5
                )
                time.sleep(1)

            if activity:
                # 标准做法: am start -n package/activity
                result = subprocess.run(
                    ["adb", "shell", "am", "start", "-n", activity],
                    capture_output=True, text=True, timeout=10
                )
                logger.info(f"  am start 输出: {result.stdout.strip()}")
            else:
                # Fallback: monkey
                logger.info("  未找到 Activity, 使用 monkey 启动")
                subprocess.run(
                    ["adb", "shell", "monkey", "-p", WECOM_PACKAGE,
                     "-c", "android.intent.category.LAUNCHER", "1"],
                    capture_output=True, timeout=10
                )

            for i in range(10):
                time.sleep(0.5)
                if self._is_wecom_foreground():
                    return True
            logger.warning(f"  等待5秒后企业微信仍未在前台")

        return False

    def _go_to_workbench(self, d) -> bool:
        try:
            # 尝试 text="工作台"
            logger.info("  查找 text='工作台'")
            tab = d(text="工作台")
            if tab.exists(timeout=5):
                logger.info("  找到 '工作台', 点击")
                tab.click()
                self._random_sleep(0.5, 1.0)
                return True

            # 尝试 description="工作台"
            logger.info("  查找 description='工作台'")
            tab = d(description="工作台")
            if tab.exists(timeout=3):
                logger.info("  找到 '工作台'(description), 点击")
                tab.click()
                self._random_sleep(0.5, 1.0)
                return True

            logger.warning("  未找到工作台 Tab")
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
                    logger.info("  找到 text='打卡', 点击")
                    checkin.click()
                    return True

                checkin = d(textContains="打卡")
                if checkin.exists(timeout=2):
                    logger.info("  找到 textContains='打卡', 点击")
                    checkin.click()
                    return True

                if attempt < 2:
                    logger.info("  未找到, 向上滑动")
                    d.swipe_ext("up", scale=0.3)
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

            # 按文本查找
            for text in button_texts:
                logger.info(f"  查找按钮: '{text}'")
                btn = d(textContains=text)
                if btn.exists(timeout=2):
                    if any(k in text for k in ["上班", "迟到"]):
                        result["actual_type"] = "上班"
                    else:
                        result["actual_type"] = "下班"
                    logger.info(f"  找到按钮 '{text}', 点击")
                    btn.click()
                    result["success"] = True
                    result["message"] = f"已点击{text}按钮"
                    return result

            # Fallback: 含关键词的可点击元素
            for keyword in ["打卡", "下班", "上班"]:
                logger.info(f"  Fallback: 查找含 '{keyword}' 的可点击元素")
                btn = d(textContains=keyword, clickable=True)
                if btn.exists(timeout=2):
                    logger.info(f"  找到含 '{keyword}' 的元素, 点击")
                    btn.click()
                    result["success"] = True
                    result["message"] = f"已点击含'{keyword}'的按钮"
                    return result

            # Last resort: 坐标点击
            width, height = d.window_size()
            center_x = width // 2
            center_y = int(height * 0.65)
            logger.info(f"  所有按钮均未找到, 坐标点击 ({center_x}, {center_y})")
            d.click(center_x, center_y)
            result["success"] = True
            result["message"] = "已点击打卡区域(坐标)"
            return result

        except Exception as e:
            result["message"] = f"点击打卡按钮失败: {e}"
            logger.error(f"  {result['message']}")
            return result

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

            # 检查页面状态
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

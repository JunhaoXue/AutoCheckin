from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ScheduleConfig(BaseModel):
    morning_time: str = "08:30"
    evening_time: str = "18:30"
    random_delay_max: int = 900
    skip_weekends: bool = True
    skip_holidays: bool = True


class CheckinLog(BaseModel):
    id: int
    checkin_type: str
    checkin_time: str
    success: bool
    trigger: str
    message: Optional[str] = None
    screenshot_path: Optional[str] = None
    created_at: str


class DeviceStatus(BaseModel):
    battery_level: int = 0
    battery_charging: bool = False
    wifi_ssid: str = ""
    wifi_ip: str = ""
    screen_on: bool = False
    adb_connected: bool = False
    uptime_seconds: int = 0


class HeartbeatMsg(BaseModel):
    type: str = "heartbeat"
    ts: str
    data: DeviceStatus


class CheckinResultData(BaseModel):
    success: bool
    checkin_type: str
    checkin_time: str
    message: str
    screenshot_b64: Optional[str] = None
    trigger: str = "scheduled"


class CheckinResultMsg(BaseModel):
    type: str = "checkin_result"
    ts: str
    msg_id: Optional[str] = None
    data: CheckinResultData


class CommandMsg(BaseModel):
    type: str
    msg_id: str
    ts: str
    data: dict = {}

import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "checkin.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_type TEXT NOT NULL,
    checkin_time TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    message TEXT,
    screenshot_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS device_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_level INTEGER,
    battery_charging INTEGER,
    wifi_ssid TEXT,
    wifi_ip TEXT,
    screen_on INTEGER,
    adb_connected INTEGER,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS schedule_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    morning_time TEXT NOT NULL DEFAULT '08:30',
    evening_time TEXT NOT NULL DEFAULT '18:30',
    random_delay_max INTEGER NOT NULL DEFAULT 900,
    skip_weekends INTEGER NOT NULL DEFAULT 1,
    skip_holidays INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_checkin_time ON checkin_logs(checkin_time);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # Ensure default schedule config exists
        await db.execute(
            "INSERT OR IGNORE INTO schedule_config (id) VALUES (1)"
        )
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

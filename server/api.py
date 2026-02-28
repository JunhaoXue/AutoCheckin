import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.responses import JSONResponse

from database import get_db
from ws_manager import manager

logger = logging.getLogger("autocheckin.api")
router = APIRouter()


# --- REST API ---

@router.get("/api/status")
async def get_status():
    """Get current device and check-in status."""
    db = await get_db()
    try:
        # Get schedule config
        cursor = await db.execute("SELECT * FROM schedule_config WHERE id = 1")
        schedule = dict(await cursor.fetchone() or {})

        # Get today's checkin logs
        today = datetime.now().strftime("%Y-%m-%d")
        cursor = await db.execute(
            "SELECT * FROM checkin_logs WHERE checkin_time LIKE ? ORDER BY checkin_time DESC",
            (f"{today}%",)
        )
        today_logs = [dict(row) for row in await cursor.fetchall()]

        return {
            "phone_online": manager.phone_online,
            "device_status": manager.last_device_status,
            "last_heartbeat": manager.last_heartbeat.isoformat() if manager.last_heartbeat else None,
            "today_checkins": manager.today_checkins,
            "today_logs": today_logs,
            "schedule": schedule,
        }
    finally:
        await db.close()


@router.get("/api/history")
async def get_history(days: int = Query(default=7, ge=1, le=90)):
    """Get check-in history for the past N days."""
    db = await get_db()
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = await db.execute(
            "SELECT * FROM checkin_logs WHERE checkin_time >= ? ORDER BY checkin_time DESC",
            (since,)
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        return {"logs": rows, "days": days}
    finally:
        await db.close()


@router.post("/api/checkin")
async def trigger_checkin(request: Request):
    """Manually trigger a check-in."""
    body = await request.json()
    checkin_type = body.get("checkin_type", "auto")

    if not manager.phone_online:
        return JSONResponse(status_code=503, content={"error": "手机未连接"})

    msg_id = await manager.send_to_phone("checkin", {"checkin_type": checkin_type})
    if not msg_id:
        return JSONResponse(status_code=500, content={"error": "发送命令失败"})

    return {"message": "打卡命令已发送", "msg_id": msg_id}


@router.post("/api/screenshot")
async def request_screenshot():
    """Request a screenshot from the phone."""
    if not manager.phone_online:
        return JSONResponse(status_code=503, content={"error": "手机未连接"})

    msg_id = await manager.send_to_phone("screenshot")
    if not msg_id:
        return JSONResponse(status_code=500, content={"error": "发送命令失败"})

    return {"message": "截图命令已发送", "msg_id": msg_id}


@router.get("/api/schedule")
async def get_schedule():
    """Get current schedule config."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM schedule_config WHERE id = 1")
        row = await cursor.fetchone()
        return dict(row) if row else {}
    finally:
        await db.close()


@router.put("/api/schedule")
async def update_schedule(request: Request):
    """Update schedule config and push to phone."""
    body = await request.json()

    db = await get_db()
    try:
        await db.execute(
            """UPDATE schedule_config SET
               morning_time = ?, evening_time = ?, random_delay_max = ?,
               skip_weekends = ?, skip_holidays = ?, updated_at = datetime('now', 'localtime')
               WHERE id = 1""",
            (body.get("morning_time", "08:30"),
             body.get("evening_time", "18:30"),
             body.get("random_delay_max", 900),
             1 if body.get("skip_weekends", True) else 0,
             1 if body.get("skip_holidays", True) else 0)
        )
        await db.commit()
    finally:
        await db.close()

    # Push to phone if online
    if manager.phone_online:
        await manager.send_to_phone("update_schedule", body)

    return {"message": "配置已更新"}


# --- WebSocket endpoints ---

@router.websocket("/ws/phone")
async def ws_phone(ws: WebSocket):
    """WebSocket endpoint for phone agent."""
    # Simple token auth
    token = ws.query_params.get("token", "")
    # Token validation can be added here
    await manager.connect_phone(ws)
    try:
        while True:
            raw = await ws.receive_text()
            await manager.handle_phone_message(raw)
    except WebSocketDisconnect:
        await manager.disconnect_phone()
    except Exception as e:
        logger.error(f"Phone WS error: {e}")
        await manager.disconnect_phone()


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    """WebSocket endpoint for browser dashboard."""
    await manager.connect_browser(ws)
    try:
        while True:
            # Browser can send commands too
            raw = await ws.receive_text()
            import json
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        await manager.disconnect_browser(ws)
    except Exception as e:
        logger.error(f"Browser WS error: {e}")
        await manager.disconnect_browser(ws)

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Query, Cookie
from fastapi.responses import JSONResponse

from database import get_db
from ws_manager import manager
from sms import sms_service
from auth import is_phone_allowed, generate_code, verify_code, verify_password, check_session, remove_session

logger = logging.getLogger("autocheckin.api")
router = APIRouter()


# --- Auth helper ---

def require_auth(request: Request):
    """Check session cookie, return phone or raise 401."""
    token = request.cookies.get("session_token", "")
    phone = check_session(token)
    if not phone:
        return None
    return phone


def auth_or_401(request: Request):
    """Return 401 JSONResponse if not authenticated."""
    if not require_auth(request):
        return JSONResponse(status_code=401, content={"error": "未登录"})
    return None


# --- Auth API (no auth required) ---

@router.post("/api/auth/send-code")
async def send_login_code(request: Request):
    """Send SMS verification code for login."""
    body = await request.json()
    phone = body.get("phone", "").strip()

    if not phone or not is_phone_allowed(phone):
        return JSONResponse(status_code=403, content={"error": "该手机号不允许登录"})

    code = generate_code(phone)
    result = sms_service.send_code_sms(phone, code)
    if result["success"]:
        return {"message": "验证码已发送"}
    return JSONResponse(status_code=500, content={"error": "短信发送失败"})


@router.post("/api/auth/login")
async def login(request: Request):
    """Verify code or password and create session."""
    body = await request.json()
    phone = body.get("phone", "").strip()
    code = body.get("code", "").strip()
    password = body.get("password", "").strip()

    if not phone:
        return JSONResponse(status_code=400, content={"error": "请填写手机号"})

    # Password login
    if password:
        token = verify_password(phone, password)
        if not token:
            return JSONResponse(status_code=401, content={"error": "手机号或密码错误"})
    # SMS code login
    elif code:
        token = verify_code(phone, code)
        if not token:
            return JSONResponse(status_code=401, content={"error": "验证码错误或已过期"})
    else:
        return JSONResponse(status_code=400, content={"error": "请填写验证码或密码"})

    response = JSONResponse(content={"message": "登录成功"})
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=86400,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/auth/logout")
async def logout(request: Request):
    """Clear session."""
    token = request.cookies.get("session_token", "")
    remove_session(token)
    response = JSONResponse(content={"message": "已退出"})
    response.delete_cookie("session_token")
    return response


# --- Protected REST API ---

@router.get("/api/status")
async def get_status(request: Request):
    """Get current device and check-in status."""
    err = auth_or_401(request)
    if err:
        return err

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM schedule_config WHERE id = 1")
        schedule = dict(await cursor.fetchone() or {})

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
async def get_history(request: Request, days: int = Query(default=7, ge=1, le=90)):
    """Get check-in history for the past N days."""
    err = auth_or_401(request)
    if err:
        return err

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


@router.get("/api/logs")
async def get_logs(request: Request, limit: int = Query(default=200, ge=1, le=1000)):
    """Get recent agent logs."""
    err = auth_or_401(request)
    if err:
        return err

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM agent_logs ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        rows.reverse()
        return {"logs": rows}
    finally:
        await db.close()


@router.post("/api/sms/wake")
async def send_wake_sms(request: Request):
    """Send SMS to wake the phone screen."""
    err = auth_or_401(request)
    if err:
        return err

    result = sms_service.send_wake_sms()
    if result["success"]:
        return {"message": "短信已发送"}
    return JSONResponse(status_code=500, content={"error": result.get("error", "发送失败")})


@router.post("/api/checkin")
async def trigger_checkin(request: Request):
    """Manually trigger a check-in. Sends SMS to wake screen first."""
    err = auth_or_401(request)
    if err:
        return err

    body = await request.json()
    checkin_type = body.get("checkin_type", "auto")

    if not manager.phone_online:
        return JSONResponse(status_code=503, content={"error": "手机未连接"})

    sms_result = sms_service.send_wake_sms()
    if sms_result["success"]:
        logger.info("Wake SMS sent, checkin command will follow")
    else:
        logger.warning(f"Wake SMS failed: {sms_result.get('error')}, proceeding anyway")

    msg_id = await manager.send_to_phone("checkin", {"checkin_type": checkin_type})
    if not msg_id:
        return JSONResponse(status_code=500, content={"error": "发送命令失败"})

    return {"message": "打卡命令已发送", "msg_id": msg_id}


@router.post("/api/screenshot")
async def request_screenshot(request: Request):
    """Request a screenshot from the phone."""
    err = auth_or_401(request)
    if err:
        return err

    if not manager.phone_online:
        return JSONResponse(status_code=503, content={"error": "手机未连接"})

    msg_id = await manager.send_to_phone("screenshot")
    if not msg_id:
        return JSONResponse(status_code=500, content={"error": "发送命令失败"})

    return {"message": "截图命令已发送", "msg_id": msg_id}


@router.get("/api/schedule")
async def get_schedule(request: Request):
    """Get current schedule config."""
    err = auth_or_401(request)
    if err:
        return err

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
    err = auth_or_401(request)
    if err:
        return err

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

    if manager.phone_online:
        await manager.send_to_phone("update_schedule", body)

    return {"message": "配置已更新"}


# --- WebSocket endpoints ---

@router.websocket("/ws/phone")
async def ws_phone(ws: WebSocket):
    """WebSocket endpoint for phone agent (no auth required)."""
    token = ws.query_params.get("token", "")
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
    """WebSocket endpoint for browser dashboard (auth via cookie)."""
    token = ws.cookies.get("session_token", "")
    if not check_session(token):
        await ws.close(code=4001, reason="未登录")
        return

    await manager.connect_browser(ws)
    try:
        while True:
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

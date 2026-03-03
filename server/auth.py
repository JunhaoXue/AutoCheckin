"""Phone number + SMS code authentication (MongoDB backed)."""

import os
import random
import string
import logging
import secrets
from datetime import datetime, timedelta

from pymongo import MongoClient

logger = logging.getLogger("autocheckin.auth")

# Allowed phone numbers from env
ALLOWED_PHONES = [p.strip() for p in os.getenv("AUTH_PHONES", "").split(",") if p.strip()]

# Password from env
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")

CODE_EXPIRE_MINUTES = 5
SESSION_EXPIRE_HOURS = 24

# MongoDB connection
_mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
_client = MongoClient(_mongo_uri)
_db = _client["autocheckin"]
_codes = _db["login_codes"]
_sessions = _db["sessions"]

# TTL indexes: MongoDB auto-deletes expired docs
_codes.create_index("expires_at", expireAfterSeconds=0)
_sessions.create_index("expires_at", expireAfterSeconds=0)
_sessions.create_index("token", unique=True)

logger.info(f"Auth: MongoDB connected, allowed phones: {len(ALLOWED_PHONES)}")


def is_phone_allowed(phone: str) -> bool:
    return phone in ALLOWED_PHONES


def generate_code(phone: str) -> str:
    """Generate a 6-digit code for a phone number."""
    code = ''.join(random.choices(string.digits, k=6))
    _codes.update_one(
        {"phone": phone},
        {"$set": {
            "code": code,
            "expires_at": datetime.utcnow() + timedelta(minutes=CODE_EXPIRE_MINUTES),
        }},
        upsert=True,
    )
    logger.info(f"Login code generated for {phone}")
    return code


def verify_code(phone: str, code: str) -> str | None:
    """Verify code, return session token on success, None on failure."""
    doc = _codes.find_one_and_delete({"phone": phone, "code": code})
    if not doc:
        return None

    # Create session
    token = secrets.token_hex(32)
    _sessions.insert_one({
        "token": token,
        "phone": phone,
        "expires_at": datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS),
    })
    logger.info(f"Login success: {phone}")
    return token


def verify_password(phone: str, password: str) -> str | None:
    """Verify phone + password, return session token on success."""
    if not is_phone_allowed(phone):
        return None
    if not AUTH_PASSWORD or password != AUTH_PASSWORD:
        return None

    token = secrets.token_hex(32)
    _sessions.insert_one({
        "token": token,
        "phone": phone,
        "expires_at": datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS),
    })
    logger.info(f"Password login success: {phone}")
    return token


def check_session(token: str) -> str | None:
    """Check session token, return phone on success, None on failure."""
    if not token:
        return None
    doc = _sessions.find_one({"token": token})
    if not doc:
        return None
    return doc["phone"]


def remove_session(token: str):
    """Remove a session (logout)."""
    _sessions.delete_one({"token": token})

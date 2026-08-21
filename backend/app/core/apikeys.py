"""Pure key-material functions: generate, parse, hash. No DB, no HTTP.

Key format (spec D2): iag_{id}_{token} where token is
secrets.token_urlsafe(32) - 43 chars, ~256 bits. token_urlsafe uses
base64url, so the token itself may contain '_' (and letters/digits);
the id is always bare digits. Parsing therefore anchors on the two
literal separators around the digit run, not on naive splitting.
"""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone

KEY_PREFIX = "iag_"
TOKEN_BYTES = 32
PREFIX_DISPLAY_LEN = 8
LAST_USED_THROTTLE_SECONDS = 60
# iag_<digits>_<token>; the token is base64url ([A-Za-z0-9_-]) and may
# itself contain underscores, so anchor on the digit run, not splitting.
_KEY_RE = re.compile(r"^iag_(\d+)_(\S+)$")


def generate_token() -> str:
    """43-char urlsafe token (~256 bits of entropy)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def build_key(key_id: int, token: str) -> str:
    return f"{KEY_PREFIX}{key_id}_{token}"


def generate_key(key_id: int) -> tuple[str, str, str]:
    """Return (full_key, key_prefix, sha256_hex_hash) for a new key."""
    full_key = build_key(key_id, generate_token())
    return full_key, display_prefix(full_key), hash_key(full_key)


def parse_key(presented: str) -> tuple[int, str] | None:
    """Extract (id, full_key) from a presented bearer value.

    Returns None for anything that is not exactly iag_{digits}_{token}.
    """
    if not presented or not presented.startswith(KEY_PREFIX):
        return None
    match = _KEY_RE.match(presented)
    if match is None:
        return None
    key_id = int(match.group(1))
    if key_id < 1:
        return None
    return key_id, presented


def hash_key(full_key: str) -> str:
    """SHA-256 hex of the full key - the only stored credential form."""
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def verify_key(presented: str, stored_hash: str) -> bool:
    """Constant-time compare of a presented key against its stored hash."""
    return hmac.compare_digest(hash_key(presented), stored_hash)


def display_prefix(full_key: str) -> str:
    """First PREFIX_DISPLAY_LEN chars incl. the iag_ prefix, e.g. 'iag_7f3a'."""
    return full_key[:PREFIX_DISPLAY_LEN]


def _naive_utc(dt: datetime) -> datetime:
    """Normalize to naive-UTC: DB columns are TIMESTAMP WITHOUT TIME ZONE
    (house contract), so comparisons must not mix aware and naive datetimes."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def is_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """True if expires_at is set and in the past. Null = never expires (D5)."""
    if expires_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return _naive_utc(expires_at) <= _naive_utc(now)

"""Password hashing and signed session tokens."""
from __future__ import annotations
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
# bcrypt is used directly (passlib 1.7.4 is unmaintained and its backend glue
# breaks with bcrypt>=5). bcrypt hashes only the first 72 bytes of a password;
# we truncate explicitly to keep that behavior across bcrypt versions.
# hashlib.scrypt is a stdlib fallback for environments without bcrypt.
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover
    _bcrypt = None
    _HAS_BCRYPT = False
_BCRYPT_MAX_BYTES = 72
def hash_password(password: str) -> str:
    if _HAS_BCRYPT:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return _bcrypt.hashpw(pw, _bcrypt.gensalt()).decode("ascii")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"
def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    if _HAS_BCRYPT and hashed.startswith("$2"):
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        try:
            return _bcrypt.checkpw(pw, hashed.encode("ascii"))
        except ValueError:
            return False
    if hashed.startswith("scrypt$"):
        _, salt_hex, dk_hex = hashed.split("$", 2)
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    return False
def new_session_token(secret: str, user_id: int, username: str, role: str, ttl_minutes: int) -> str:
    """Stateless signed token: base64url(payload).base64url(hmac)."""
    import base64
    import json
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"
def verify_session_token(secret: str, token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body_b64, sig = token.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    import base64
    import json
    try:
        payload = json.loads(base64.urlsafe_b64decode(body_b64))
    except (ValueError, UnicodeDecodeError):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
        return None
    return payload
def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

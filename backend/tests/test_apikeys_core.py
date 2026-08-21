"""Phase A unit tests: pure key-material functions (no DB, no HTTP)."""
from __future__ import annotations
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app.core import apikeys


def test_generate_key_shape():
    full, prefix, key_hash = apikeys.generate_key(12)
    assert full.startswith("iag_12_")
    assert len(full) == len("iag_12_") + 43
    assert prefix == full[: apikeys.PREFIX_DISPLAY_LEN]
    assert prefix.startswith("iag_12")
    assert len(key_hash) == 64
    assert key_hash == hashlib.sha256(full.encode()).hexdigest()


def test_generate_key_randomness():
    a = apikeys.generate_key(1)[0]
    b = apikeys.generate_key(1)[0]
    assert a != b


def test_parse_key_roundtrip():
    full, _, _ = apikeys.generate_key(7)
    parsed = apikeys.parse_key(full)
    assert parsed == (7, full)


def test_parse_key_token_with_underscore():
    # token_urlsafe output may itself contain '_': the regex anchors on
    # the digit run between the literal separators, not naive splitting.
    presented = "iag_3_Ab_cD-eF_gH"
    assert apikeys.parse_key(presented) == (3, presented)


def test_parse_key_malformed():
    for bad in ["", "iag_", "iag_x_y", "iag_0_token", "iag_-1_token",
                "iag_1", "iag_1_", "XAG_1_token", "iag_1_token extra",
                "iag_12", "junk", "iag__token"]:
        assert apikeys.parse_key(bad) is None, bad


def test_verify_key_constant_time_compare():
    full, _, stored = apikeys.generate_key(5)
    assert apikeys.verify_key(full, stored) is True
    assert apikeys.verify_key(full + "x", stored) is False
    # hash_key is deterministic; verify reuses it under compare_digest
    assert hmac.compare_digest(apikeys.hash_key(full), stored)


def test_display_prefix():
    assert apikeys.display_prefix("iag_123_abcdefghij") == "iag_123_"
    assert apikeys.display_prefix("iag_1_abc") == "iag_1_ab"


def test_is_expired():
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    assert apikeys.is_expired(None, now) is False
    assert apikeys.is_expired(now + timedelta(days=1), now) is False
    assert apikeys.is_expired(now - timedelta(seconds=1), now) is True
    assert apikeys.is_expired(now, now) is True  # boundary: expired at == now
    # naive expires_at (as stored in DB) vs aware now must not raise
    assert apikeys.is_expired(datetime(2026, 1, 1), now) is True


def test_last_used_throttle_constant():
    assert apikeys.LAST_USED_THROTTLE_SECONDS == 60

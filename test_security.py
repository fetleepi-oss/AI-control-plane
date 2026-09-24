import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth.security import (
    hash_password, verify_password, create_access_token, decode_access_token,
    generate_api_key, hash_api_key,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_jwt_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_jwt_rejects_garbage():
    assert decode_access_token("not-a-real-token") is None


def test_api_key_never_recoverable_from_hash():
    raw, key_hash, prefix = generate_api_key()
    assert raw.startswith("sk-live-")
    assert hash_api_key(raw) == key_hash
    assert raw not in key_hash  # the hash must not leak the raw key
    assert prefix == raw[:12]

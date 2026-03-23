import json
import base64
from scripts.lib.auth import sign_jwt, build_claims


def test_sign_jwt_produces_three_part_token():
    token = sign_jwt(
        secret="test-secret",
        claims={"sub": "alice@test.com", "client_id": "claude-code"}
    )
    parts = token.split(".")
    assert len(parts) == 3  # header.payload.signature


def test_sign_jwt_contains_claims():
    token = sign_jwt(
        secret="test-secret",
        claims={"sub": "alice@test.com", "agent": "myproject"}
    )
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert payload["sub"] == "alice@test.com"
    assert payload["agent"] == "myproject"
    assert "iat" in payload
    assert "exp" in payload


def test_sign_jwt_sets_expiry():
    token = sign_jwt(secret="s", claims={"sub": "a"}, ttl_seconds=3600)
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert payload["exp"] - payload["iat"] == 3600


def test_build_claims_structure():
    config = {
        "userId": "ruben@example.com",
        "agentName": "yoda",
        "clientId": "claude-code",
    }
    hook_input = {"session_id": "sess-abc123"}
    claims = build_claims(config, hook_input)

    assert claims["sub"] == "ruben@example.com"
    assert claims["client_id"] == "claude-code"
    assert claims["sender"] == "claude-code:ruben@example.com"
    assert claims["agent"] == "yoda"
    assert claims["channel"] == "claude-code"
    assert claims["topic"] == "sess-abc123"


def test_build_claims_defaults():
    config = {"userId": "bob@example.com"}
    hook_input = {}
    claims = build_claims(config, hook_input)

    assert claims["sub"] == "bob@example.com"
    assert claims["client_id"] == "claude-code"
    assert claims["agent"] == "unknown"
    assert claims["topic"] == ""

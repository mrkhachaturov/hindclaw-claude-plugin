import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(secret: str, claims: dict, ttl_seconds: int = 3600) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    claims = {**claims, "iat": now, "exp": now + ttl_seconds}
    payload = _b64url(json.dumps(claims).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def build_claims(config: dict, hook_input: dict) -> dict:
    user_id = config["userId"]
    agent = config.get("agentName", "unknown")
    return {
        "sub": user_id,
        "client_id": config.get("clientId", "claude-code"),
        "sender": f"claude-code:{user_id}",
        "agent": agent,
        "channel": "claude-code",
        "topic": hook_input.get("session_id", ""),
    }

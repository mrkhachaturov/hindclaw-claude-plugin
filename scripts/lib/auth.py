"""JWT signing with stdlib HMAC-SHA256.

Zero-dependency JWT implementation for signing per-request tokens.
Uses only Python stdlib (hmac, base64, json). The hindclaw server
decodes these tokens to resolve user identity and permissions.
"""

import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    """Base64url-encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(secret: str, claims: dict, ttl_seconds: int = 3600) -> str:
    """Sign a JWT with HMAC-SHA256.

    Produces a three-part token (header.payload.signature) with ``iat``
    and ``exp`` claims injected automatically.

    Args:
        secret: HMAC-SHA256 shared secret.
        claims: Payload claims to include (sub, client_id, sender, etc.).
        ttl_seconds: Token lifetime in seconds (default 1 hour).

    Returns:
        Signed JWT string.
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    claims = {**claims, "iat": now, "exp": now + ttl_seconds}
    payload = _b64url(json.dumps(claims).encode())
    sig_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def build_claims(config: dict, hook_input: dict) -> dict:
    """Construct JWT claims from plugin config and hook input.

    Builds the full claims dict for server-side identity resolution:
    ``sender`` is ``claude-code:{userId}`` which the HindclawTenant
    extension parses to look up the user via ``get_user_by_channel()``.

    Args:
        config: Merged plugin config with userId, agentName, clientId.
        hook_input: Claude Code hook input with session_id.

    Returns:
        Claims dict with sub, client_id, sender, agent, channel, topic.
    """
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

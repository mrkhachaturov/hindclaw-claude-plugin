"""Hindsight HTTP client for the HindClaw Claude Code plugin.

Zero-dependency HTTP client using only Python stdlib (urllib.request).
Handles authentication via JWT signed with HMAC-SHA256, and raises
HindclawHttpError for non-2xx responses so callers can branch on
status_code (e.g. 403 for permission denied).
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from scripts.lib.auth import sign_jwt


# ---
# Exceptions
# ---

class HindclawHttpError(Exception):
    """Raised when the Hindsight API returns a non-2xx response.

    Attributes:
        status_code: HTTP status code returned by the server.
        body: Response body, parsed as JSON dict if possible, raw string otherwise.
    """

    def __init__(self, status_code: int, body: dict | str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HindclawHttpError {status_code}: {body}")


# ---
# URL validation
# ---

def _validate_api_url(url: str) -> str:
    """Strip trailing slashes and verify the URL scheme is http or https.

    Args:
        url: Raw API URL string to validate.

    Returns:
        Cleaned URL with trailing slashes removed.

    Raises:
        ValueError: If the URL is empty, has no valid scheme, or uses a
            scheme other than http or https.
    """
    if not url:
        raise ValueError("API URL must not be empty")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"API URL scheme must be http or https, got: {parsed.scheme!r}"
        )

    return url.rstrip("/")


# ---
# Client
# ---

class HindclawClient:
    """HTTP client for the Hindsight memory API.

    Uses stdlib urllib — zero external dependencies. Every authenticated
    request calls ``claims_builder()`` to get fresh claims, then signs a
    short-lived JWT.

    Args:
        api_url: Base URL of the Hindsight API (e.g. ``https://mem.example.com``).
            Trailing slashes are stripped automatically.
        jwt_secret: HMAC-SHA256 shared secret used to sign per-request JWTs.
        claims_builder: Callable that returns a claims dict. Called fresh on
            every authenticated request so the token always reflects the
            current session context.
    """

    def __init__(self, api_url: str, jwt_secret: str, claims_builder):
        self.api_url = _validate_api_url(api_url)
        self.jwt_secret = jwt_secret
        self.claims_builder = claims_builder

    # ---
    # Internal helpers
    # ---

    def _auth_header(self) -> str:
        """Build a fresh Bearer token for the current request.

        Returns:
            Authorization header value: ``Bearer <signed-jwt>``.
        """
        claims = self.claims_builder()
        token = sign_jwt(self.jwt_secret, claims)
        return f"Bearer {token}"

    def _post(self, path: str, body: dict, *, auth: bool, timeout: int) -> dict:
        """Perform a POST request and return the parsed JSON response.

        Args:
            path: URL path to append to the base API URL.
            body: Request body to send as JSON.
            auth: Whether to attach an Authorization header.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            HindclawHttpError: If the server returns a non-2xx status.
        """
        url = f"{self.api_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", self._auth_header())

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.fp.read() if exc.fp else b""
            try:
                body_parsed = json.loads(raw)
            except (ValueError, AttributeError):
                body_parsed = raw.decode(errors="replace")
            raise HindclawHttpError(exc.code, body_parsed) from exc

    # ---
    # Public API
    # ---

    def health_check(self, timeout: int = 5) -> bool:
        """Check whether the Hindsight API is reachable.

        Sends an unauthenticated GET to ``/health``. Returns False on any
        error (connection refused, timeout, non-2xx) so callers never need
        to handle exceptions.

        Args:
            timeout: Request timeout in seconds.

        Returns:
            True if the server responds with 2xx, False otherwise.
        """
        url = f"{self.api_url}/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except Exception:
            return False

    def recall(
        self,
        bank_id: str,
        query: str,
        budget: str = "mid",
        max_tokens: int = 1024,
        types: list[str] | None = None,
        timeout: int = 10,
    ) -> dict:
        """Recall memories matching a query from a bank.

        Args:
            bank_id: Target bank identifier.
            query: Natural-language query string.
            budget: Retrieval budget — ``"low"``, ``"mid"``, or ``"high"``.
            max_tokens: Maximum tokens to return.
            types: Memory types to filter on (e.g. ``["world", "experience"]``).
                Defaults to ``["world", "experience"]`` when not specified.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response dict from the recall endpoint.

        Raises:
            HindclawHttpError: If the server returns a non-2xx response.
                Check ``status_code == 403`` for permission denied.
        """
        if types is None:
            types = ["world", "experience"]

        body = {
            "query": query,
            "budget": budget,
            "max_tokens": max_tokens,
            "types": types,
        }
        path = f"/v1/default/banks/{bank_id}/memories/recall"
        return self._post(path, body, auth=True, timeout=timeout)

    def retain(
        self,
        bank_id: str,
        items: list[dict],
        async_: bool = True,
        timeout: int = 15,
    ) -> dict:
        """Persist memory items into a bank.

        Args:
            bank_id: Target bank identifier.
            items: List of memory item dicts (each with at least ``content``).
            async_: Whether the server should process retention asynchronously.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response dict from the retain endpoint.

        Raises:
            HindclawHttpError: If the server returns a non-2xx response.
                Check ``status_code == 403`` for permission denied.
        """
        body = {
            "items": items,
            "async": async_,
        }
        path = f"/v1/default/banks/{bank_id}/memories"
        return self._post(path, body, auth=True, timeout=timeout)

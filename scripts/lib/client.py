"""Hindsight HTTP client for the HindClaw Claude Code plugin.

Zero-dependency HTTP client using only Python stdlib (urllib.request).
Authenticates with a static API key via Bearer token header.
"""

import json
import urllib.error
import urllib.parse
import urllib.request


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


def _validate_api_url(url: str) -> str:
    """Strip trailing slashes and verify the URL scheme is http or https."""
    if not url:
        raise ValueError("API URL must not be empty")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"API URL scheme must be http or https, got: {parsed.scheme!r}")
    return url.rstrip("/")


class HindclawClient:
    """HTTP client for the Hindsight memory API.

    Uses stdlib urllib — zero external dependencies. Authenticates with
    a static API key sent as a Bearer token on every request.

    Args:
        api_url: Base URL of the Hindsight API (e.g. ``http://hindsight.office:8888``).
        api_key: HindClaw API key (``hc_sa_*`` or ``hc_u_*``).
    """

    def __init__(self, api_url: str, api_key: str):
        self.api_url = _validate_api_url(api_url)
        if not api_key:
            raise ValueError("API key must not be empty")
        self.api_key = api_key

    def _auth_header(self) -> str:
        """Return the Authorization header value."""
        return f"Bearer {self.api_key}"

    def _post(self, path: str, body: dict, *, auth: bool, timeout: int) -> dict:
        """Perform a POST request and return the parsed JSON response."""
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

    def health_check(self, timeout: int = 5) -> bool:
        """Check whether the Hindsight API is reachable."""
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
        timeout: int = 10,
    ) -> dict:
        """Recall memories matching a query from a bank."""
        body = {
            "query": query,
            "budget": budget,
            "max_tokens": max_tokens,
        }
        path = f"/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}/memories/recall"
        return self._post(path, body, auth=True, timeout=timeout)

    def retain(
        self,
        bank_id: str,
        items: list[dict],
        async_: bool = True,
        timeout: int = 15,
    ) -> dict:
        """Persist memory items into a bank."""
        body = {
            "items": items,
            "async": async_,
        }
        path = f"/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}/memories"
        return self._post(path, body, auth=True, timeout=timeout)

    def create_bank(
        self,
        bank_id: str,
        template: str,
        timeout: int = 10,
    ) -> dict:
        """Create a bank from a template via the HindClaw extension API."""
        body = {
            "bank_id": bank_id,
            "template": template,
        }
        return self._post("/ext/hindclaw/banks", body, auth=True, timeout=timeout)

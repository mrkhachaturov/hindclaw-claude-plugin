"""Tests for the HindclawClient HTTP client.

Covers: health check, recall, retain, URL validation, and error handling.
All HTTP calls are mocked via unittest.mock.patch on urllib.request.urlopen.
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status: int, body: dict | str) -> MagicMock:
    """Build a mock urlopen response with a read() method."""
    if isinstance(body, dict):
        data = json.dumps(body).encode()
    else:
        data = body.encode() if isinstance(body, str) else body
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = data
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _make_http_error(status: int, body: dict | str) -> urllib.error.HTTPError:
    """Build a urllib HTTPError for non-2xx responses."""
    if isinstance(body, dict):
        data = json.dumps(body).encode()
    else:
        data = body.encode() if isinstance(body, str) else body
    return urllib.error.HTTPError(
        url="http://test",
        code=status,
        msg="Error",
        hdrs=None,
        fp=BytesIO(data),
    )


def _make_claims_builder(claims: dict | None = None):
    """Return a simple claims_builder callable for testing."""
    def builder():
        return claims or {"sub": "test@example.com", "client_id": "claude-code"}
    return builder


# ---------------------------------------------------------------------------
# URL validation tests
# ---------------------------------------------------------------------------

class TestValidateApiUrl:
    def test_valid_http_url_accepted(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("http://hindclaw.example.com")
        assert result == "http://hindclaw.example.com"

    def test_valid_https_url_accepted(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("https://hindclaw.example.com")
        assert result == "https://hindclaw.example.com"

    def test_trailing_slash_stripped(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("https://hindclaw.example.com/")
        assert result == "https://hindclaw.example.com"

    def test_multiple_trailing_slashes_stripped(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("https://hindclaw.example.com///")
        assert result == "https://hindclaw.example.com"

    def test_path_with_trailing_slash_stripped(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("https://hindclaw.example.com/api/")
        assert result == "https://hindclaw.example.com/api"

    def test_invalid_scheme_raises_value_error(self):
        from scripts.lib.client import _validate_api_url
        with pytest.raises(ValueError, match="scheme"):
            _validate_api_url("ftp://hindclaw.example.com")

    def test_empty_string_raises_value_error(self):
        from scripts.lib.client import _validate_api_url
        with pytest.raises(ValueError):
            _validate_api_url("")

    def test_no_scheme_raises_value_error(self):
        from scripts.lib.client import _validate_api_url
        with pytest.raises(ValueError):
            _validate_api_url("hindclaw.example.com")

    def test_url_with_port_accepted(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("http://localhost:8080")
        assert result == "http://localhost:8080"

    def test_url_with_port_and_trailing_slash_stripped(self):
        from scripts.lib.client import _validate_api_url
        result = _validate_api_url("http://localhost:8080/")
        assert result == "http://localhost:8080"


# ---------------------------------------------------------------------------
# HindclawHttpError tests
# ---------------------------------------------------------------------------

class TestHindclawHttpError:
    def test_error_stores_status_code_and_body(self):
        from scripts.lib.client import HindclawHttpError
        err = HindclawHttpError(403, {"detail": "Forbidden"})
        assert err.status_code == 403
        assert err.body == {"detail": "Forbidden"}

    def test_error_str_contains_status_code(self):
        from scripts.lib.client import HindclawHttpError
        err = HindclawHttpError(500, "Internal Server Error")
        assert "500" in str(err)

    def test_403_is_detectable(self):
        from scripts.lib.client import HindclawHttpError
        err = HindclawHttpError(403, {"detail": "Permission denied"})
        assert err.status_code == 403


# ---------------------------------------------------------------------------
# HindclawClient construction tests
# ---------------------------------------------------------------------------

class TestHindclawClientConstruction:
    def test_client_stores_api_url(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)
        assert client.api_url == "https://api.example.com"

    def test_client_strips_trailing_slash_on_construction(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com/", "secret", cb)
        assert client.api_url == "https://api.example.com"

    def test_client_stores_jwt_secret(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "my-secret", cb)
        assert client.jwt_secret == "my-secret"

    def test_client_stores_claims_builder(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)
        assert client.claims_builder is cb

    def test_invalid_url_raises_on_construction(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        with pytest.raises(ValueError):
            HindclawClient("ftp://api.example.com", "secret", cb)


# ---------------------------------------------------------------------------
# health_check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_returns_true_on_200(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)

        mock_resp = _make_response(200, {"status": "ok"})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.health_check()

        assert result is True

    def test_health_check_returns_false_on_connection_error(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)

        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            result = client.health_check()

        assert result is False

    def test_health_check_returns_false_on_http_error(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)

        with patch("urllib.request.urlopen", side_effect=_make_http_error(503, "Service Unavailable")):
            result = client.health_check()

        assert result is False

    def test_health_check_hits_correct_url(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)

        mock_resp = _make_response(200, {"status": "ok"})
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.health_check()

        call_args = mock_open.call_args
        req = call_args[0][0]
        assert req.full_url == "https://api.example.com/health"

    def test_health_check_has_no_auth_header(self):
        from scripts.lib.client import HindclawClient
        cb = _make_claims_builder()
        client = HindclawClient("https://api.example.com", "secret", cb)

        mock_resp = _make_response(200, {"status": "ok"})
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.health_check()

        call_args = mock_open.call_args
        req = call_args[0][0]
        assert req.get_header("Authorization") is None


# ---------------------------------------------------------------------------
# recall tests
# ---------------------------------------------------------------------------

class TestRecall:
    def _client(self):
        from scripts.lib.client import HindclawClient
        return HindclawClient(
            "https://api.example.com",
            "test-secret",
            _make_claims_builder(),
        )

    def test_recall_returns_dict_on_200(self):
        client = self._client()
        body = {"results": [{"content": "fact 1"}, {"content": "fact 2"}]}
        mock_resp = _make_response(200, body)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.recall("my-bank", "what is X?")

        assert result == body

    def test_recall_hits_correct_endpoint(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "what is X?")

        req = mock_open.call_args[0][0]
        assert req.full_url == "https://api.example.com/v1/default/banks/my-bank/memories/recall"

    def test_recall_uses_post_method(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "what is X?")

        req = mock_open.call_args[0][0]
        assert req.get_method() == "POST"

    def test_recall_sends_correct_body(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "test query", budget="high", max_tokens=2048, types=["world"])

        req = mock_open.call_args[0][0]
        sent_body = json.loads(req.data)
        assert sent_body["query"] == "test query"
        assert sent_body["budget"] == "high"
        assert sent_body["max_tokens"] == 2048
        assert sent_body["types"] == ["world"]

    def test_recall_default_body_fields(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "test query")

        req = mock_open.call_args[0][0]
        sent_body = json.loads(req.data)
        assert sent_body["budget"] == "mid"
        assert sent_body["max_tokens"] == 1024
        # types should be present (default value)
        assert "types" in sent_body

    def test_recall_sets_content_type_header(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "query")

        req = mock_open.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"

    def test_recall_sets_authorization_header(self):
        client = self._client()
        mock_resp = _make_response(200, {"results": []})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.recall("my-bank", "query")

        req = mock_open.call_args[0][0]
        auth = req.get_header("Authorization")
        assert auth is not None
        assert auth.startswith("Bearer ")

    def test_recall_raises_hindclaw_http_error_on_403(self):
        from scripts.lib.client import HindclawHttpError
        client = self._client()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(403, {"detail": "Permission denied"})):
            with pytest.raises(HindclawHttpError) as exc_info:
                client.recall("my-bank", "query")

        assert exc_info.value.status_code == 403

    def test_recall_raises_hindclaw_http_error_on_500(self):
        from scripts.lib.client import HindclawHttpError
        client = self._client()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(500, "Internal Server Error")):
            with pytest.raises(HindclawHttpError) as exc_info:
                client.recall("my-bank", "query")

        assert exc_info.value.status_code == 500

    def test_recall_error_body_is_captured(self):
        from scripts.lib.client import HindclawHttpError
        client = self._client()
        error_body = {"detail": "Bank not found"}

        with patch("urllib.request.urlopen", side_effect=_make_http_error(404, error_body)):
            with pytest.raises(HindclawHttpError) as exc_info:
                client.recall("my-bank", "query")

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# retain tests
# ---------------------------------------------------------------------------

class TestRetain:
    def _client(self):
        from scripts.lib.client import HindclawClient
        return HindclawClient(
            "https://api.example.com",
            "test-secret",
            _make_claims_builder(),
        )

    def test_retain_returns_dict_on_200(self):
        client = self._client()
        body = {"accepted": 2, "rejected": 0}
        mock_resp = _make_response(200, body)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.retain("my-bank", [{"content": "fact", "context": "claude-code"}])

        assert result == body

    def test_retain_hits_correct_endpoint(self):
        client = self._client()
        mock_resp = _make_response(200, {"accepted": 1})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.retain("my-bank", [{"content": "fact"}])

        req = mock_open.call_args[0][0]
        assert req.full_url == "https://api.example.com/v1/default/banks/my-bank/memories"

    def test_retain_uses_post_method(self):
        client = self._client()
        mock_resp = _make_response(200, {"accepted": 1})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.retain("my-bank", [{"content": "fact"}])

        req = mock_open.call_args[0][0]
        assert req.get_method() == "POST"

    def test_retain_sends_correct_body(self):
        client = self._client()
        mock_resp = _make_response(200, {"accepted": 1})
        items = [{"content": "fact 1", "context": "claude-code"}, {"content": "fact 2"}]

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.retain("my-bank", items, async_=True)

        req = mock_open.call_args[0][0]
        sent_body = json.loads(req.data)
        assert sent_body["items"] == items
        assert sent_body["async"] is True

    def test_retain_async_false(self):
        client = self._client()
        mock_resp = _make_response(200, {"accepted": 1})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.retain("my-bank", [{"content": "fact"}], async_=False)

        req = mock_open.call_args[0][0]
        sent_body = json.loads(req.data)
        assert sent_body["async"] is False

    def test_retain_sets_authorization_header(self):
        client = self._client()
        mock_resp = _make_response(200, {"accepted": 1})

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client.retain("my-bank", [{"content": "fact"}])

        req = mock_open.call_args[0][0]
        auth = req.get_header("Authorization")
        assert auth is not None
        assert auth.startswith("Bearer ")

    def test_retain_raises_hindclaw_http_error_on_403(self):
        from scripts.lib.client import HindclawHttpError
        client = self._client()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(403, {"detail": "Permission denied"})):
            with pytest.raises(HindclawHttpError) as exc_info:
                client.retain("my-bank", [{"content": "fact"}])

        assert exc_info.value.status_code == 403

    def test_retain_raises_hindclaw_http_error_on_500(self):
        from scripts.lib.client import HindclawHttpError
        client = self._client()

        with patch("urllib.request.urlopen", side_effect=_make_http_error(500, "Server Error")):
            with pytest.raises(HindclawHttpError) as exc_info:
                client.retain("my-bank", [{"content": "fact"}])

        assert exc_info.value.status_code == 500

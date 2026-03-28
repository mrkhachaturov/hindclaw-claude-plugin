"""Tests for HindclawClient with API key auth."""

import json
import unittest
from unittest.mock import patch, MagicMock

from scripts.lib.client import HindclawClient, HindclawHttpError


class TestClientConstructor(unittest.TestCase):
    def test_stores_api_url_stripped(self):
        c = HindclawClient("http://example.com/", "hc_sa_test")
        self.assertEqual(c.api_url, "http://example.com")

    def test_stores_api_key(self):
        c = HindclawClient("http://example.com", "hc_sa_test")
        self.assertEqual(c.api_key, "hc_sa_test")

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            HindclawClient("", "hc_sa_test")

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            HindclawClient("ftp://example.com", "hc_sa_test")

    def test_rejects_empty_api_key(self):
        with self.assertRaises(ValueError):
            HindclawClient("http://example.com", "")


class TestAuthHeader(unittest.TestCase):
    def test_bearer_token_uses_api_key(self):
        c = HindclawClient("http://example.com", "hc_sa_mykey123")
        self.assertEqual(c._auth_header(), "Bearer hc_sa_mykey123")


class TestHealthCheck(unittest.TestCase):
    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_returns_true_on_success(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        c = HindclawClient("http://example.com", "hc_sa_test")
        self.assertTrue(c.health_check())

    @patch("scripts.lib.client.urllib.request.urlopen", side_effect=Exception("refused"))
    def test_returns_false_on_error(self, mock_urlopen):
        c = HindclawClient("http://example.com", "hc_sa_test")
        self.assertFalse(c.health_check())


class TestRecall(unittest.TestCase):
    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_sends_auth_header(self, mock_urlopen):
        resp_data = json.dumps({"results": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = HindclawClient("http://example.com", "hc_sa_test")
        c.recall("bank1", "query")

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer hc_sa_test")

    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_sends_budget_and_max_tokens(self, mock_urlopen):
        resp_data = json.dumps({"results": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = HindclawClient("http://example.com", "hc_sa_test")
        c.recall("bank1", "query", budget="high", max_tokens=2048)

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body["budget"], "high")
        self.assertEqual(body["max_tokens"], 2048)

    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_raises_on_403(self, mock_urlopen):
        err = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "http://example.com", 403, "Forbidden", {}, None
        )
        mock_urlopen.side_effect = err
        c = HindclawClient("http://example.com", "hc_sa_test")
        with self.assertRaises(HindclawHttpError) as ctx:
            c.recall("bank1", "query")
        self.assertEqual(ctx.exception.status_code, 403)


class TestRetain(unittest.TestCase):
    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_sends_items_with_async(self, mock_urlopen):
        resp_data = json.dumps({"ok": True}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = HindclawClient("http://example.com", "hc_sa_test")
        c.retain("bank1", [{"content": "text"}])

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body["items"], [{"content": "text"}])
        self.assertTrue(body["async"])


class TestCreateBank(unittest.TestCase):
    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_posts_to_ext_hindclaw_banks(self, mock_urlopen):
        resp_data = json.dumps({"bank_id": "test", "bank_created": True}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = HindclawClient("http://example.com", "hc_sa_test")
        result = c.create_bank("my::bank", "fullstack-dev")

        req = mock_urlopen.call_args[0][0]
        self.assertIn("/ext/hindclaw/banks", req.full_url)
        body = json.loads(req.data)
        self.assertEqual(body["bank_id"], "my::bank")
        self.assertEqual(body["template"], "fullstack-dev")

    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_raises_on_404_template_not_found(self, mock_urlopen):
        err = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "http://example.com", 404, "Not Found", {}, None
        )
        mock_urlopen.side_effect = err
        c = HindclawClient("http://example.com", "hc_sa_test")
        with self.assertRaises(HindclawHttpError) as ctx:
            c.create_bank("my::bank", "bad-template")
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_raises_on_403_no_permission(self, mock_urlopen):
        err = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "http://example.com", 403, "Forbidden", {}, None
        )
        mock_urlopen.side_effect = err
        c = HindclawClient("http://example.com", "hc_sa_test")
        with self.assertRaises(HindclawHttpError) as ctx:
            c.create_bank("my::bank", "dev")
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("scripts.lib.client.urllib.request.urlopen")
    def test_raises_on_422_validation_error(self, mock_urlopen):
        err = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "http://example.com", 422, "Unprocessable", {}, None
        )
        mock_urlopen.side_effect = err
        c = HindclawClient("http://example.com", "hc_sa_test")
        with self.assertRaises(HindclawHttpError) as ctx:
            c.create_bank("my::bank", "dev")
        self.assertEqual(ctx.exception.status_code, 422)

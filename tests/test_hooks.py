"""End-to-end integration tests for the HindClaw Claude Code hook scripts.

Imports each hook module in-process via importlib and mocks stdin/stdout/HTTP
using unittest.mock.patch -- the same technique as upstream test_hooks.py.
subprocess.run() is deliberately avoided: monkeypatching does not cross process
boundaries.

All tests use API key auth (no JWT). The v2 state shape is:
  {healthy, turn_count, error_notified, config_warned, bank_created}
"""

import importlib.util
import io
import json
import os
import urllib.error
from unittest.mock import patch

import pytest


# ---
# Fake HTTP helpers
# ---


class FakeHTTPResponse:
    """Mock for urllib.request.urlopen responses.

    Args:
        body: Response body dict (JSON-encoded) or raw bytes.
        status: HTTP status code to expose as .status and .code.
    """

    def __init__(self, body, status=200):
        self.body = json.dumps(body).encode() if isinstance(body, dict) else body
        self.status = status
        self.code = status

    def read(self):
        """Return the raw response bytes."""
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def make_http_error(status, body=None):
    """Create a urllib.error.HTTPError that the client code can catch.

    Args:
        status: HTTP status code (e.g. 403).
        body: Optional response body dict; encoded to JSON bytes.

    Returns:
        urllib.error.HTTPError instance with the given status and body.
    """
    body_bytes = json.dumps(body or {}).encode()
    fp = io.BytesIO(body_bytes)
    return urllib.error.HTTPError(
        url="http://fake:9077",
        code=status,
        msg=f"HTTP {status}",
        hdrs={},
        fp=fp,
    )


# ---
# Default settings
# ---

_DEFAULT_SETTINGS = {
    "hindsightApiUrl": "http://fake:9077",
    "apiKey": "hc_sa_test_key_000",
    "bankId": "test-bank",
    "template": None,
    "autoRecall": True,
    "autoRetain": True,
    "retainEveryNTurns": 1,
    "retainOverlapTurns": 1,
    "retainContext": "claude-code",
    "retainRoles": ["user", "assistant"],
    "recallBudget": "mid",
    "recallMaxTokens": 1024,
    "recallContextTurns": 1,
    "recallMaxQueryChars": 800,
    "recallTopK": None,
    "debug": False,
}


# ---
# Core runner
# ---


def _run_hook(module_name, hook_input, tmp_path, urlopen_side_effect=None, extra_settings=None):
    """Import and run a hook script's main() with mocked stdin/stdout/HTTP.

    Each call gets an isolated plugin_root and plugin_data directory under
    tmp_path, so sessions never bleed across tests.

    Args:
        module_name: Filename stem of the script to load (e.g. ``"recall"``).
        hook_input: Dict that will be JSON-serialised and fed to stdin.
        tmp_path: pytest tmp_path fixture providing an isolated temp directory.
        urlopen_side_effect: Optional callable or exception to use as the
            side_effect for the urllib.request.urlopen patch.  Defaults to a
            lambda that returns a FakeHTTPResponse with an empty results list.
        extra_settings: Optional dict merged (shallowly) into the default
            settings.json written to plugin_root before the hook runs.

    Returns:
        Tuple of ``(stdout_str, stderr_str)`` captured during the run.
    """
    plugin_root = tmp_path / "plugin_root"
    plugin_data = tmp_path / "plugin_data"
    plugin_root.mkdir(exist_ok=True)
    plugin_data.mkdir(exist_ok=True)

    settings = dict(_DEFAULT_SETTINGS)
    if extra_settings:
        settings.update(extra_settings)
    (plugin_root / "settings.json").write_text(json.dumps(settings))

    stdin_data = io.StringIO(json.dumps(hook_input))
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(scripts_dir, f"{module_name}.py")
    )
    mod = importlib.util.module_from_spec(spec)

    default_response = FakeHTTPResponse({"results": []})
    side_effect = urlopen_side_effect or (lambda *a, **kw: default_response)

    env = {
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
    }
    # Strip real HINDCLAW_* env vars so they do not bleed into tests.
    clean_env = dict(os.environ)
    for k in list(clean_env):
        if k.startswith("HINDCLAW_"):
            del clean_env[k]
    clean_env.update(env)

    with patch.dict(os.environ, clean_env, clear=True):
        with patch("sys.stdin", stdin_data), \
             patch("sys.stdout", stdout_capture), \
             patch("sys.stderr", stderr_capture), \
             patch("urllib.request.urlopen", side_effect=side_effect):
            spec.loader.exec_module(mod)
            mod.main()

    return stdout_capture.getvalue(), stderr_capture.getvalue()


def _read_state(tmp_path, session_id):
    """Read the persisted state JSON for a session.

    Returns the parsed dict or None if the file does not exist.
    """
    state_file = tmp_path / "plugin_data" / "state" / f"{session_id}.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return None


def _write_state(tmp_path, session_id, state):
    """Pre-create a session state file for hooks that read it."""
    state_dir = tmp_path / "plugin_data" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{session_id}.json"
    state_file.write_text(json.dumps(state))


def _make_transcript_jsonl(tmp_path, messages):
    """Write a JSONL transcript in Claude Code nested format.

    Args:
        tmp_path: Directory to write the transcript file into.
        messages: List of ``{"role": str, "content": str}`` dicts.

    Returns:
        Absolute path string of the created transcript file.
    """
    transcript_file = tmp_path / "transcript.jsonl"
    lines = []
    for msg in messages:
        entry = {"type": msg["role"], "message": {"role": msg["role"], "content": msg["content"]}}
        lines.append(json.dumps(entry))
    transcript_file.write_text("\n".join(lines))
    return str(transcript_file)


# ---
# TestSessionStartHook
# ---


class TestSessionStartHook:
    def test_missing_api_key_outputs_system_message(self, tmp_path):
        """Missing apiKey -> systemMessage listing apiKey, state healthy: false."""
        hook_input = {"session_id": "ses-start-nokey", "cwd": "/tmp/project"}

        stdout, _ = _run_hook("session_start", hook_input, tmp_path,
                              extra_settings={"apiKey": ""})

        assert stdout, "Expected systemMessage output when apiKey is missing"
        parsed = json.loads(stdout)
        assert "systemMessage" in parsed
        assert "apiKey" in parsed["systemMessage"]

        state = _read_state(tmp_path, "ses-start-nokey")
        assert state is not None
        assert state["healthy"] is False

    def test_missing_bank_id_outputs_system_message(self, tmp_path):
        """Missing bankId -> systemMessage mentioning bankId."""
        hook_input = {"session_id": "ses-start-nobank", "cwd": "/tmp/project"}

        stdout, _ = _run_hook("session_start", hook_input, tmp_path,
                              extra_settings={"bankId": ""})

        assert stdout, "Expected systemMessage output when bankId is missing"
        parsed = json.loads(stdout)
        assert "systemMessage" in parsed
        assert "bankId" in parsed["systemMessage"]

        state = _read_state(tmp_path, "ses-start-nobank")
        assert state is not None
        assert state["healthy"] is False

    def test_health_check_passes_writes_healthy_state(self, tmp_path):
        """Health check success -> state healthy: true, no systemMessage."""
        hook_input = {"session_id": "ses-start-ok", "cwd": "/tmp/project"}

        def urlopen_stub(*args, **kwargs):
            return FakeHTTPResponse({"status": "ok"})

        stdout, _ = _run_hook("session_start", hook_input, tmp_path,
                              urlopen_side_effect=urlopen_stub)

        state = _read_state(tmp_path, "ses-start-ok")
        assert state is not None
        assert state["healthy"] is True
        assert state["turn_count"] == 0
        assert state["error_notified"] is False
        assert state["config_warned"] is False
        assert state["bank_created"] is False

        # No systemMessage on success
        assert stdout == ""

    def test_health_check_fails_writes_unhealthy_state_and_system_message(self, tmp_path):
        """Health check failure -> state healthy: false, systemMessage output."""
        hook_input = {"session_id": "ses-start-fail", "cwd": "/tmp/project"}

        def urlopen_stub(*args, **kwargs):
            raise OSError("Connection refused")

        stdout, _ = _run_hook("session_start", hook_input, tmp_path,
                              urlopen_side_effect=urlopen_stub)

        state = _read_state(tmp_path, "ses-start-fail")
        assert state is not None
        assert state["healthy"] is False

        assert stdout, "Expected systemMessage when health check fails"
        parsed = json.loads(stdout)
        assert "systemMessage" in parsed
        assert "cannot reach" in parsed["systemMessage"]


# ---
# TestRecallHook
# ---


class TestRecallHook:
    def _setup_healthy_session(self, tmp_path, session_id):
        """Pre-create a healthy session state so recall does not skip."""
        _write_state(tmp_path, session_id, {
            "healthy": True,
            "turn_count": 0,
            "error_notified": False,
            "config_warned": False,
            "bank_created": False,
        })

    def test_outputs_additional_context_when_memories_found(self, tmp_path):
        """Recall with results returns hookSpecificOutput JSON with hindsight_memories."""
        session_id = "ses-recall-found"
        self._setup_healthy_session(tmp_path, session_id)

        results = [{"text": "Paris is in France", "type": "world", "mentioned_at": "2025-01-01"}]
        response = FakeHTTPResponse({"results": results})

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is the capital of France?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response)

        assert stdout, "Expected output on stdout when memories are found"
        parsed = json.loads(stdout)
        assert "hookSpecificOutput" in parsed
        assert "additionalContext" in parsed["hookSpecificOutput"]
        assert "hindsight_memories" in parsed["hookSpecificOutput"]["additionalContext"]
        assert parsed["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def test_no_output_when_no_memories(self, tmp_path):
        """Recall with empty results emits nothing to stdout."""
        session_id = "ses-recall-empty"
        self._setup_healthy_session(tmp_path, session_id)

        response = FakeHTTPResponse({"results": []})

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is the capital of Germany?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response)

        assert stdout == "", "Expected empty stdout when no memories returned"

    def test_403_outputs_system_message_and_error_context(self, tmp_path):
        """403 from recall -> systemMessage + additionalContext with hindsight_error,
        state has error_notified: true and healthy: false."""
        session_id = "ses-recall-403"
        self._setup_healthy_session(tmp_path, session_id)

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is the speed of light?",
        }

        def raise_403(*a, **kw):
            raise make_http_error(403, {"detail": "Forbidden"})

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=raise_403)

        assert stdout, "Expected output on 403"
        parsed = json.loads(stdout)
        assert "systemMessage" in parsed
        assert "denied" in parsed["systemMessage"].lower() or "403" in parsed["systemMessage"]
        assert "hookSpecificOutput" in parsed
        assert "hindsight_error" in parsed["hookSpecificOutput"]["additionalContext"]

        state = _read_state(tmp_path, session_id)
        assert state["error_notified"] is True
        assert state["healthy"] is False

    def test_401_outputs_system_message_and_error_context(self, tmp_path):
        """401 from recall -> same behavior as 403."""
        session_id = "ses-recall-401"
        self._setup_healthy_session(tmp_path, session_id)

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is quantum mechanics?",
        }

        def raise_401(*a, **kw):
            raise make_http_error(401, {"detail": "Unauthorized"})

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=raise_401)

        assert stdout, "Expected output on 401"
        parsed = json.loads(stdout)
        assert "systemMessage" in parsed
        assert "hookSpecificOutput" in parsed
        assert "hindsight_error" in parsed["hookSpecificOutput"]["additionalContext"]

        state = _read_state(tmp_path, session_id)
        assert state["error_notified"] is True
        assert state["healthy"] is False

    def test_recall_with_warnings_surfaces_system_message(self, tmp_path):
        """Server warnings in response -> systemMessage with warning text,
        memories in additionalContext, state has config_warned: true."""
        session_id = "ses-recall-warn"
        self._setup_healthy_session(tmp_path, session_id)

        results = [{"text": "The sun is a star", "type": "world"}]
        response_body = {
            "results": results,
            "warnings": ["budget 'ultra' capped to 'high'", "max_tokens 4096 capped to 2048"],
        }
        response = FakeHTTPResponse(response_body)

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "Tell me about the sun",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response)

        assert stdout, "Expected output when warnings present"
        parsed = json.loads(stdout)

        # Should have both systemMessage (warning) and memories
        assert "systemMessage" in parsed
        assert "budget" in parsed["systemMessage"] or "capped" in parsed["systemMessage"]
        assert "hookSpecificOutput" in parsed
        assert "hindsight_memories" in parsed["hookSpecificOutput"]["additionalContext"]

        state = _read_state(tmp_path, session_id)
        assert state["config_warned"] is True

    def test_unhealthy_session_skips_recall(self, tmp_path):
        """Unhealthy session -> no API call, empty stdout."""
        session_id = "ses-recall-unhealthy"
        _write_state(tmp_path, session_id, {
            "healthy": False,
            "turn_count": 0,
            "error_notified": False,
            "config_warned": False,
            "bank_created": False,
        })

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"results": []})

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is the meaning of life?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=capture_call)

        assert stdout == "", "Expected empty stdout for unhealthy session"
        assert len(captured_calls) == 0, "No API call should be made for unhealthy session"

    def test_disabled_auto_recall_produces_no_output(self, tmp_path):
        """autoRecall: false -> empty stdout, no API call."""
        session_id = "ses-recall-disabled"
        self._setup_healthy_session(tmp_path, session_id)

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"results": [{"text": "Something"}]})

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "What is the answer to life?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=capture_call,
                              extra_settings={"autoRecall": False})

        assert stdout == "", "Expected empty stdout when autoRecall is false"
        assert len(captured_calls) == 0, "No API call when autoRecall is false"

    def test_short_prompt_skips_recall(self, tmp_path):
        """Prompt < 5 chars -> no API call, empty stdout."""
        session_id = "ses-recall-short"
        self._setup_healthy_session(tmp_path, session_id)

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"results": []})

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "prompt": "Hi",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=capture_call)

        assert stdout == "", "Expected empty stdout for prompt shorter than 5 chars"
        assert len(captured_calls) == 0, "No API call for short prompt"


# ---
# TestRetainHook
# ---


class TestRetainHook:
    def _setup_healthy_session(self, tmp_path, session_id, turn_count=0):
        """Pre-create a healthy session state so retain does not skip."""
        _write_state(tmp_path, session_id, {
            "healthy": True,
            "turn_count": turn_count,
            "error_notified": False,
            "config_warned": False,
            "bank_created": False,
        })

    def test_retain_calls_api_on_nth_turn(self, tmp_path):
        """Healthy session, Nth turn -> retain API called."""
        session_id = "ses-retain-nth"
        # retainEveryNTurns=1 means every turn. Pre-set turn_count=0 so after
        # increment it becomes 1, and 1 % 1 == 0 -> retain fires.
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Tell me about Paris"},
            {"role": "assistant", "content": "Paris is the capital of France"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        captured_calls = []

        def capture_call(*args, **kwargs):
            req = args[0]
            body = json.loads(req.data)
            captured_calls.append(body)
            return FakeHTTPResponse({"accepted": 1})

        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=capture_call)

        assert len(captured_calls) == 1, "Expected exactly one retain API call"
        body = captured_calls[0]
        assert "items" in body
        assert len(body["items"]) == 1
        assert "Paris" in body["items"][0]["content"]
        assert body.get("async") is True

    def test_non_nth_turn_skips_retain(self, tmp_path):
        """With retainEveryNTurns=5, turn 1 -> no call."""
        session_id = "ses-retain-skip"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"accepted": 1})

        # retainEveryNTurns=5 means only turns 5, 10, 15... trigger a retain.
        # After increment: turn_count=1, 1 % 5 != 0 -> skip.
        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=capture_call,
                  extra_settings={"retainEveryNTurns": 5})

        assert len(captured_calls) == 0, "Expected no API call on turn 1 when retainEveryNTurns=5"

    def test_404_with_template_creates_bank_and_retries(self, tmp_path):
        """404 on retain + template configured -> create_bank called, retain retried."""
        session_id = "ses-retain-404-tmpl"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Tell me about machine learning"},
            {"role": "assistant", "content": "Machine learning is a subset of AI"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        call_sequence = []

        def route_calls(*args, **kwargs):
            req = args[0]
            url = req.full_url
            body = json.loads(req.data)
            call_sequence.append({"url": url, "body": body})

            # First call: retain -> 404
            if "/memories" in url and len([c for c in call_sequence if "/memories" in c["url"]]) == 1:
                raise make_http_error(404, {"detail": "Bank not found"})
            # Second call: create_bank -> 200
            if "/ext/hindclaw/banks" in url:
                return FakeHTTPResponse({"bank_id": "test-bank"})
            # Third call: retry retain -> 200
            return FakeHTTPResponse({"accepted": 1})

        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=route_calls,
                  extra_settings={"template": "default-template"})

        urls = [c["url"] for c in call_sequence]
        assert len(call_sequence) == 3, f"Expected 3 calls (retain, create_bank, retry retain), got {len(call_sequence)}: {urls}"

        # First: retain attempt (404)
        assert "/memories" in urls[0]
        # Second: create_bank
        assert "/ext/hindclaw/banks" in urls[1]
        assert call_sequence[1]["body"]["template"] == "default-template"
        assert call_sequence[1]["body"]["bank_id"] == "test-bank"
        # Third: retry retain
        assert "/memories" in urls[2]

        state = _read_state(tmp_path, session_id)
        assert state["bank_created"] is True

    def test_404_without_template_marks_unhealthy(self, tmp_path):
        """404 on retain + no template -> mark unhealthy, systemMessage output."""
        session_id = "ses-retain-404-notmpl"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Tell me about AI safety"},
            {"role": "assistant", "content": "AI safety is important"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        def raise_404(*args, **kwargs):
            raise make_http_error(404, {"detail": "Bank not found"})

        stdout, stderr = _run_hook("retain", hook_input, tmp_path,
                                   urlopen_side_effect=raise_404,
                                   extra_settings={"template": None})

        state = _read_state(tmp_path, session_id)
        assert state["healthy"] is False
        assert "not found" in stderr.lower() or "template" in stderr.lower()
        # systemMessage output for user notification
        output = json.loads(stdout)
        assert "systemMessage" in output
        assert "template" in output["systemMessage"].lower()

    def test_409_on_bank_creation_treated_as_success(self, tmp_path):
        """409 on create_bank -> treat as already exists, retry retain."""
        session_id = "ses-retain-409"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Explain quantum computing"},
            {"role": "assistant", "content": "Quantum computing uses qubits"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        call_sequence = []

        def route_calls(*args, **kwargs):
            req = args[0]
            url = req.full_url
            body = json.loads(req.data)
            call_sequence.append({"url": url, "body": body})

            # First retain -> 404
            if "/memories" in url and len([c for c in call_sequence if "/memories" in c["url"]]) == 1:
                raise make_http_error(404, {"detail": "Bank not found"})
            # create_bank -> 409
            if "/ext/hindclaw/banks" in url:
                raise make_http_error(409, {"detail": "Already exists"})
            # Retry retain -> 200
            return FakeHTTPResponse({"accepted": 1})

        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=route_calls,
                  extra_settings={"template": "default-template"})

        urls = [c["url"] for c in call_sequence]
        assert len(call_sequence) == 3, f"Expected 3 calls (retain, create_bank, retry), got {len(call_sequence)}: {urls}"

        state = _read_state(tmp_path, session_id)
        assert state["bank_created"] is True
        assert state["healthy"] is True

    def test_422_on_bank_creation_marks_unhealthy(self, tmp_path):
        """422 on create_bank -> mark unhealthy."""
        session_id = "ses-retain-422"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Tell me about Docker"},
            {"role": "assistant", "content": "Docker is a containerization platform"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        call_sequence = []

        def route_calls(*args, **kwargs):
            req = args[0]
            url = req.full_url
            call_sequence.append(url)

            # First retain -> 404
            if "/memories" in url and call_sequence.count(url) == 1:
                raise make_http_error(404, {"detail": "Bank not found"})
            # create_bank -> 422
            if "/ext/hindclaw/banks" in url:
                raise make_http_error(422, {"detail": "Invalid bank config"})
            return FakeHTTPResponse({"accepted": 1})

        stdout, stderr = _run_hook("retain", hook_input, tmp_path,
                                    urlopen_side_effect=route_calls,
                                    extra_settings={"template": "default-template"})

        state = _read_state(tmp_path, session_id)
        assert state["healthy"] is False
        assert "422" in stderr or "validation" in stderr.lower()
        # systemMessage output for user notification
        output = json.loads(stdout)
        assert "systemMessage" in output

    def test_401_on_retain_marks_unhealthy(self, tmp_path):
        """401 on retain -> mark unhealthy."""
        session_id = "ses-retain-401"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Explain neural networks"},
            {"role": "assistant", "content": "Neural networks are computing systems"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        def raise_401(*args, **kwargs):
            raise make_http_error(401, {"detail": "Unauthorized"})

        stdout, stderr = _run_hook("retain", hook_input, tmp_path,
                                    urlopen_side_effect=raise_401)

        state = _read_state(tmp_path, session_id)
        assert state["healthy"] is False
        assert "401" in stderr or "denied" in stderr.lower()
        # systemMessage output for user notification
        output = json.loads(stdout)
        assert "systemMessage" in output
        assert "denied" in output["systemMessage"].lower()

    def test_403_on_retain_marks_unhealthy(self, tmp_path):
        """403 on retain -> mark unhealthy."""
        session_id = "ses-retain-403"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "What is Kubernetes?"},
            {"role": "assistant", "content": "Kubernetes is a container orchestrator"},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        def raise_403(*args, **kwargs):
            raise make_http_error(403, {"detail": "Forbidden"})

        stdout, stderr = _run_hook("retain", hook_input, tmp_path,
                                    urlopen_side_effect=raise_403)

        state = _read_state(tmp_path, session_id)
        assert state["healthy"] is False
        assert "403" in stderr or "denied" in stderr.lower()
        # systemMessage output for user notification
        output = json.loads(stdout)
        assert "systemMessage" in output
        assert "denied" in output["systemMessage"].lower()

    def test_disabled_auto_retain_does_not_call_api(self, tmp_path):
        """autoRetain: false -> no API call."""
        session_id = "ses-retain-disabled"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "How do I bake bread?"},
            {"role": "assistant", "content": "You need flour, yeast, water and salt."},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"accepted": 1})

        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=capture_call,
                  extra_settings={"autoRetain": False})

        assert len(captured_calls) == 0, "Expected no API call when autoRetain is false"

    def test_retain_no_stdout_output(self, tmp_path):
        """Stop hook produces no stdout (fire-and-forget)."""
        session_id = "ses-retain-silent"
        self._setup_healthy_session(tmp_path, session_id, turn_count=0)

        transcript_path = _make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "What is the meaning of life?"},
            {"role": "assistant", "content": "The meaning of life is 42."},
        ])

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        stdout, _ = _run_hook("retain", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: FakeHTTPResponse({"accepted": 1}))

        assert stdout == "", "Expected empty stdout for retain (fire-and-forget Stop hook)"


# ---
# TestSessionEndHook
# ---


class TestSessionEndHook:
    def test_deletes_state_file(self, tmp_path):
        """Cleanup removes the session state file."""
        session_id = "ses-end-1"
        _write_state(tmp_path, session_id, {
            "healthy": True,
            "turn_count": 3,
            "error_notified": False,
            "config_warned": False,
            "bank_created": False,
        })

        state_file = tmp_path / "plugin_data" / "state" / f"{session_id}.json"
        assert state_file.exists(), "Pre-condition: state file must exist before SessionEnd"

        hook_input = {
            "session_id": session_id,
            "cwd": "/tmp/project",
        }

        # session_end has no HTTP calls; side_effect will never be invoked.
        _run_hook("session_end", hook_input, tmp_path)

        assert not state_file.exists(), "Expected state file to be deleted after SessionEnd"

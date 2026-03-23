"""End-to-end integration tests for the HindClaw Claude Code hook scripts.

Imports each hook module in-process via importlib and mocks stdin/stdout/HTTP
using unittest.mock.patch — the same technique as upstream test_hooks.py.
subprocess.run() is deliberately avoided: monkeypatching does not cross process
boundaries.
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

    settings = {
        "autoRecall": True,
        "autoRetain": True,
        "retainEveryNTurns": 1,
        "hindsightApiUrl": "http://fake:9077",
        "jwtSecret": "test-secret",
        "userId": "test@test.com",
        "agentName": "test-project",
    }
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


# ---
# TestRecallHook
# ---


class TestRecallHook:
    def test_outputs_additional_context_when_memories_found(self, tmp_path):
        """Recall with results returns hookSpecificOutput JSON."""
        results = [{"text": "Paris is in France", "type": "world", "mentioned_at": "2025-01-01"}]
        response = FakeHTTPResponse({"results": results})

        hook_input = {
            "session_id": "ses-recall-1",
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

    def test_no_output_when_no_memories(self, tmp_path):
        """Recall with empty results emits nothing to stdout."""
        response = FakeHTTPResponse({"results": []})

        hook_input = {
            "session_id": "ses-recall-2",
            "cwd": "/tmp/project",
            "prompt": "What is the capital of Germany?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response)

        assert stdout == "", "Expected empty stdout when no memories returned"

    def test_no_output_for_short_prompt(self, tmp_path):
        """Prompt < 5 chars produces no output."""
        hook_input = {
            "session_id": "ses-recall-3",
            "cwd": "/tmp/project",
            "prompt": "Hi",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path)

        assert stdout == "", "Expected empty stdout for prompt shorter than 5 chars"

    def test_output_format_matches_claude_code_spec(self, tmp_path):
        """Validates hookEventName and additionalContext keys."""
        results = [{"text": "The sky is blue", "type": "world"}]
        response = FakeHTTPResponse({"results": results})

        hook_input = {
            "session_id": "ses-recall-4",
            "cwd": "/tmp/project",
            "prompt": "Tell me something about the sky",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response)

        parsed = json.loads(stdout)
        hook_specific = parsed["hookSpecificOutput"]
        assert hook_specific["hookEventName"] == "UserPromptSubmit"
        assert isinstance(hook_specific["additionalContext"], str)
        assert len(hook_specific["additionalContext"]) > 0

    def test_empty_output_on_403(self, tmp_path):
        """403 from recall -> no stdout, warning on stderr."""
        hook_input = {
            "session_id": "ses-recall-5",
            "cwd": "/tmp/project",
            "prompt": "What is the speed of light?",
        }

        stdout, stderr = _run_hook("recall", hook_input, tmp_path,
                                   urlopen_side_effect=lambda *a, **kw: (_ for _ in ()).throw(
                                       make_http_error(403, {"detail": "Forbidden"})
                                   ))

        assert stdout == "", "Expected empty stdout on 403"
        assert "403" in stderr or "denied" in stderr.lower(), \
            "Expected 403 or 'denied' in stderr warning"

    def test_graceful_on_api_error(self, tmp_path):
        """OSError degrades silently."""
        hook_input = {
            "session_id": "ses-recall-6",
            "cwd": "/tmp/project",
            "prompt": "What is the boiling point of water?",
        }

        def raise_os_error(*a, **kw):
            raise OSError("Connection refused")

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=raise_os_error)

        assert stdout == "", "Expected empty stdout on OSError"

    def test_disabled_auto_recall_produces_no_output(self, tmp_path):
        """autoRecall: false -> empty stdout."""
        results = [{"text": "Something relevant", "type": "world"}]
        response = FakeHTTPResponse({"results": results})

        hook_input = {
            "session_id": "ses-recall-7",
            "cwd": "/tmp/project",
            "prompt": "What is the answer to life?",
        }

        stdout, _ = _run_hook("recall", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: response,
                              extra_settings={"autoRecall": False})

        assert stdout == "", "Expected empty stdout when autoRecall is false"


# ---
# TestRetainHook
# ---


class TestRetainHook:
    def _make_transcript_jsonl(self, tmp_path, messages):
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

    def test_posts_transcript_to_hindsight(self, tmp_path):
        """Retain reads JSONL and calls API with content."""
        transcript_path = self._make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Tell me about Paris"},
            {"role": "assistant", "content": "Paris is the capital of France"},
        ])

        hook_input = {
            "session_id": "ses-retain-1",
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

        assert len(captured_calls) == 1, "Expected exactly one API call"
        body = captured_calls[0]
        assert "items" in body
        assert len(body["items"]) == 1
        # Content should include text from the transcript
        assert "Paris" in body["items"][0]["content"]

    def test_no_retain_on_empty_transcript(self, tmp_path):
        """Nonexistent transcript -> no API call."""
        hook_input = {
            "session_id": "ses-retain-2",
            "cwd": "/tmp/project",
            "transcript_path": "/nonexistent/path/transcript.jsonl",
        }

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"accepted": 0})

        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=capture_call)

        assert len(captured_calls) == 0, "Expected no API call for missing transcript"

    def test_chunked_retain_skips_below_threshold(self, tmp_path):
        """With retainEveryNTurns=5, turn 1 -> no call."""
        transcript_path = self._make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ])

        hook_input = {
            "session_id": "ses-retain-3",
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        captured_calls = []

        def capture_call(*args, **kwargs):
            captured_calls.append(args)
            return FakeHTTPResponse({"accepted": 1})

        # retainEveryNTurns=5 means only turns 5, 10, 15… trigger a retain.
        # This is the first call, so turn_count=1, and 1 % 5 != 0 → skip.
        _run_hook("retain", hook_input, tmp_path,
                  urlopen_side_effect=capture_call,
                  extra_settings={"retainEveryNTurns": 5})

        assert len(captured_calls) == 0, "Expected no API call on turn 1 when retainEveryNTurns=5"

    def test_retain_no_stdout_output(self, tmp_path):
        """Stop hook produces no stdout."""
        transcript_path = self._make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "What is the meaning of life?"},
            {"role": "assistant", "content": "The meaning of life is 42."},
        ])

        hook_input = {
            "session_id": "ses-retain-4",
            "cwd": "/tmp/project",
            "transcript_path": transcript_path,
        }

        stdout, _ = _run_hook("retain", hook_input, tmp_path,
                              urlopen_side_effect=lambda *a, **kw: FakeHTTPResponse({"accepted": 1}))

        assert stdout == "", "Expected empty stdout for retain (fire-and-forget Stop hook)"

    def test_retain_posts_async_true(self, tmp_path):
        """Body contains 'async': true."""
        transcript_path = self._make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "Explain quantum entanglement"},
            {"role": "assistant", "content": "Quantum entanglement is a phenomenon where particles are correlated."},
        ])

        hook_input = {
            "session_id": "ses-retain-5",
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

        assert len(captured_calls) == 1
        assert captured_calls[0].get("async") is True, "Expected 'async': true in retain request body"

    def test_disabled_auto_retain_does_not_call_api(self, tmp_path):
        """autoRetain: false -> no API call."""
        transcript_path = self._make_transcript_jsonl(tmp_path, [
            {"role": "user", "content": "How do I bake bread?"},
            {"role": "assistant", "content": "You need flour, yeast, water and salt."},
        ])

        hook_input = {
            "session_id": "ses-retain-6",
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


# ---
# TestSessionStartHook
# ---


class TestSessionStartHook:
    def test_writes_healthy_state_on_success(self, tmp_path):
        """Health check success -> state file with healthy: true."""
        hook_input = {
            "session_id": "ses-start-1",
            "cwd": "/tmp/project",
        }

        plugin_data = tmp_path / "plugin_data"
        plugin_data.mkdir(exist_ok=True)
        state_dir = plugin_data / "state"

        # Health check hits /health — return 200
        def urlopen_stub(*args, **kwargs):
            return FakeHTTPResponse({"status": "ok"})

        _run_hook("session_start", hook_input, tmp_path,
                  urlopen_side_effect=urlopen_stub)

        state_file = state_dir / "ses-start-1.json"
        assert state_file.exists(), "Expected state file to be written on SessionStart"
        state = json.loads(state_file.read_text())
        assert state.get("healthy") is True, "Expected healthy: true after successful health check"

    def test_writes_unhealthy_state_on_failure(self, tmp_path):
        """Health check failure -> state file with healthy: false."""
        hook_input = {
            "session_id": "ses-start-2",
            "cwd": "/tmp/project",
        }

        plugin_data = tmp_path / "plugin_data"
        plugin_data.mkdir(exist_ok=True)
        state_dir = plugin_data / "state"

        def urlopen_stub(*args, **kwargs):
            raise OSError("Connection refused")

        _run_hook("session_start", hook_input, tmp_path,
                  urlopen_side_effect=urlopen_stub)

        state_file = state_dir / "ses-start-2.json"
        assert state_file.exists(), "Expected state file to be written even on health check failure"
        state = json.loads(state_file.read_text())
        assert state.get("healthy") is False, "Expected healthy: false after failed health check"


# ---
# TestSessionEndHook
# ---


class TestSessionEndHook:
    def test_deletes_state_file(self, tmp_path):
        """Cleanup removes the session state file."""
        plugin_data = tmp_path / "plugin_data"
        state_dir = plugin_data / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Pre-create the state file that SessionEnd should delete.
        state_file = state_dir / "ses-end-1.json"
        state_file.write_text(json.dumps({"healthy": True, "denied_banks": [], "turn_count": 3}))
        assert state_file.exists(), "Pre-condition: state file must exist before SessionEnd"

        hook_input = {
            "session_id": "ses-end-1",
            "cwd": "/tmp/project",
        }

        # session_end has no HTTP calls; side_effect will never be invoked.
        _run_hook("session_end", hook_input, tmp_path)

        assert not state_file.exists(), "Expected state file to be deleted after SessionEnd"

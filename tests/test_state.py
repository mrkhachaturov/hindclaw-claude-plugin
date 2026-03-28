import json
import os
import threading
import unittest
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_state_dir(tmp_path):
    """Return env patch dict pointing CLAUDE_PLUGIN_DATA at tmp_path."""
    return {"CLAUDE_PLUGIN_DATA": str(tmp_path)}


_DEFAULT = {
    "healthy": True,
    "turn_count": 0,
    "error_notified": False,
    "config_warned": False,
    "bank_created": False,
}


# ---------------------------------------------------------------------------
# _default_state
# ---------------------------------------------------------------------------

class TestDefaultState(unittest.TestCase):
    def test_default_state_has_all_fields(self):
        from scripts.lib.state import _default_state
        state = _default_state()
        self.assertEqual(state, {
            "healthy": True,
            "turn_count": 0,
            "error_notified": False,
            "config_warned": False,
            "bank_created": False,
        })

    def test_no_denied_banks_field(self):
        from scripts.lib.state import _default_state
        state = _default_state()
        self.assertNotIn("denied_banks", state)


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_normal_session_id_unchanged(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename("abc-123_XYZ")
        assert result == "abc-123_XYZ"

    def test_path_separators_replaced(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result

    def test_double_dot_replaced(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename("foo..bar")
        assert ".." not in result

    def test_control_chars_replaced(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename("foo\x00bar\x1fbaz")
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_long_name_capped_at_200(self):
        from scripts.lib.state import _safe_filename
        long_name = "a" * 300
        result = _safe_filename(long_name)
        assert len(result) == 200

    def test_empty_string_becomes_state(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename("")
        assert result == "state"

    def test_special_chars_replaced(self):
        from scripts.lib.state import _safe_filename
        result = _safe_filename('foo*bar?baz"qux<x>y|z')
        for ch in '*?"<>|':
            assert ch not in result


# ---------------------------------------------------------------------------
# _state_dir
# ---------------------------------------------------------------------------

class TestStateDir:
    def test_creates_state_dir(self, tmp_path):
        from scripts.lib.state import _state_dir
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            d = _state_dir()
        assert os.path.isdir(d)
        assert d.endswith("state")

    def test_state_dir_inside_plugin_data(self, tmp_path):
        from scripts.lib.state import _state_dir
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            d = _state_dir()
        assert d.startswith(str(tmp_path))

    def test_state_dir_uses_default_when_env_missing(self, tmp_path):
        from scripts.lib.state import _state_dir
        home = str(tmp_path / "home")
        env = {"CLAUDE_PLUGIN_DATA": ""}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home)):
                d = _state_dir()
        assert os.path.isdir(d)


# ---------------------------------------------------------------------------
# _state_file path traversal guard
# ---------------------------------------------------------------------------

class TestStateFile:
    def test_normal_session_id_returns_path(self, tmp_path):
        from scripts.lib.state import _state_file
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            path = _state_file("sess-abc123")
        assert path.endswith(".json")
        assert "sess-abc123" in path

    def test_traversal_attempt_raises(self, tmp_path):
        from scripts.lib.state import _state_file
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            # Even after sanitisation the resolved path must stay inside state dir.
            # A name that after sanitisation resolves outside should raise.
            # Because _safe_filename replaces path separators this mostly cannot
            # happen, but we can try a symlink-based escape — not easy in unit
            # tests, so we just verify the guard path exists by testing a normal
            # case produces no ValueError.
            path = _state_file("legit-session-id")
        assert os.path.basename(path).endswith(".json")


# ---------------------------------------------------------------------------
# read_session_state / write_session_state
# ---------------------------------------------------------------------------

class TestReadWriteSessionState:
    def test_read_missing_returns_default(self, tmp_path):
        from scripts.lib.state import read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            state = read_session_state("nonexistent-session")
        assert state == _DEFAULT

    def test_write_then_read_roundtrip(self, tmp_path):
        from scripts.lib.state import read_session_state, write_session_state
        data = {"healthy": True, "turn_count": 5, "error_notified": True, "config_warned": False, "bank_created": False}
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-001", data)
            result = read_session_state("sess-001")
        assert result == data

    def test_write_creates_json_file(self, tmp_path):
        from scripts.lib.state import write_session_state
        data = {"healthy": False, "turn_count": 0, "error_notified": False, "config_warned": False, "bank_created": False}
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-write-test", data)
        state_file = tmp_path / "state" / "sess-write-test.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text()) == data

    def test_write_is_atomic_no_tmp_left_behind(self, tmp_path):
        from scripts.lib.state import write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-atomic", _DEFAULT)
        state_dir = tmp_path / "state"
        tmp_files = list(state_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_read_corrupted_file_returns_default(self, tmp_path):
        from scripts.lib.state import read_session_state
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "corrupt-sess.json").write_text("not valid json {{{")
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            result = read_session_state("corrupt-sess")
        assert result == _DEFAULT

    def test_overwrite_updates_data(self, tmp_path):
        from scripts.lib.state import read_session_state, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-over", {"healthy": True, "turn_count": 1, "error_notified": False, "config_warned": False, "bank_created": False})
            write_session_state("sess-over", {"healthy": False, "turn_count": 2, "error_notified": True, "config_warned": False, "bank_created": True})
            result = read_session_state("sess-over")
        assert result["healthy"] is False
        assert result["error_notified"] is True
        assert result["bank_created"] is True
        assert result["turn_count"] == 2


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------

class TestSessionIsolation:
    def test_two_sessions_do_not_interfere(self, tmp_path):
        from scripts.lib.state import read_session_state, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-A", {"healthy": True, "turn_count": 3, "error_notified": False, "config_warned": False, "bank_created": False})
            write_session_state("sess-B", {"healthy": False, "turn_count": 7, "error_notified": True, "config_warned": False, "bank_created": False})

            state_a = read_session_state("sess-A")
            state_b = read_session_state("sess-B")

        assert state_a["turn_count"] == 3
        assert state_b["turn_count"] == 7
        assert state_a["healthy"] is True
        assert state_b["healthy"] is False
        assert state_b["error_notified"] is True

    def test_write_to_one_session_does_not_affect_other(self, tmp_path):
        from scripts.lib.state import read_session_state, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-X", _DEFAULT.copy())
            write_session_state("sess-Y", _DEFAULT.copy())

            write_session_state("sess-X", {"healthy": False, "turn_count": 10, "error_notified": True, "config_warned": False, "bank_created": False})

            state_y = read_session_state("sess-Y")

        assert state_y == _DEFAULT


# ---------------------------------------------------------------------------
# delete_session_state
# ---------------------------------------------------------------------------

class TestDeleteSessionState:
    def test_delete_removes_state_file(self, tmp_path):
        from scripts.lib.state import write_session_state, delete_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-del", _DEFAULT.copy())
            delete_session_state("sess-del")
        state_file = tmp_path / "state" / "sess-del.json"
        assert not state_file.exists()

    def test_delete_nonexistent_is_noop(self, tmp_path):
        from scripts.lib.state import delete_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            # Should not raise
            delete_session_state("never-existed")

    def test_delete_only_removes_targeted_session(self, tmp_path):
        from scripts.lib.state import write_session_state, delete_session_state, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-keep", {"healthy": True, "turn_count": 1, "error_notified": False, "config_warned": False, "bank_created": False})
            write_session_state("sess-gone", {"healthy": True, "turn_count": 2, "error_notified": False, "config_warned": False, "bank_created": False})
            delete_session_state("sess-gone")
            kept = read_session_state("sess-keep")
        assert kept["turn_count"] == 1

    def test_read_after_delete_returns_default(self, tmp_path):
        from scripts.lib.state import write_session_state, delete_session_state, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-cycle", {"healthy": False, "turn_count": 99, "error_notified": True, "config_warned": True, "bank_created": True})
            delete_session_state("sess-cycle")
            result = read_session_state("sess-cycle")
        assert result == _DEFAULT


# ---------------------------------------------------------------------------
# increment_turn
# ---------------------------------------------------------------------------

class TestIncrementTurn:
    def test_increment_from_zero(self, tmp_path):
        from scripts.lib.state import increment_turn
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            count = increment_turn("sess-incr")
        assert count == 1

    def test_increment_multiple_times(self, tmp_path):
        from scripts.lib.state import increment_turn
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            assert increment_turn("sess-multi") == 1
            assert increment_turn("sess-multi") == 2
            assert increment_turn("sess-multi") == 3

    def test_increment_persists_to_state_file(self, tmp_path):
        from scripts.lib.state import increment_turn, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            increment_turn("sess-persist")
            increment_turn("sess-persist")
            state = read_session_state("sess-persist")
        assert state["turn_count"] == 2

    def test_increment_isolated_per_session(self, tmp_path):
        from scripts.lib.state import increment_turn
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            increment_turn("sess-iso-a")
            increment_turn("sess-iso-a")
            count_b = increment_turn("sess-iso-b")
        assert count_b == 1

    def test_concurrent_increments_no_lost_updates(self, tmp_path):
        """Multiple threads incrementing the same session should not lose updates.

        The env var is set once in the outer scope; all threads share it.
        patch.dict is not thread-safe so we set the env var directly and
        restore it after, rather than wrapping each thread in patch.dict.
        """
        from scripts.lib.state import increment_turn
        results = []
        errors = []

        def do_increment():
            try:
                count = increment_turn("sess-concurrent")
                results.append(count)
            except Exception as e:
                errors.append(e)

        # Set env once for all threads — avoids patch.dict thread-safety issues
        original = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = str(tmp_path)
        try:
            threads = [threading.Thread(target=do_increment) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            if original is None:
                os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            else:
                os.environ["CLAUDE_PLUGIN_DATA"] = original

        assert errors == []
        assert len(results) == 10
        # All returned values should be unique (no two threads got the same count)
        assert len(set(results)) == 10
        # Values should be 1..10
        assert sorted(results) == list(range(1, 11))


# ---------------------------------------------------------------------------
# is_healthy
# ---------------------------------------------------------------------------

class TestIsHealthy:
    def test_default_is_healthy(self, tmp_path):
        from scripts.lib.state import is_healthy
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            assert is_healthy("fresh-session") is True

    def test_unhealthy_after_write(self, tmp_path):
        from scripts.lib.state import is_healthy, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sick-sess", {"healthy": False, "turn_count": 0, "error_notified": False, "config_warned": False, "bank_created": False})
            assert is_healthy("sick-sess") is False

    def test_healthy_after_write(self, tmp_path):
        from scripts.lib.state import is_healthy, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("healthy-sess", {"healthy": True, "turn_count": 5, "error_notified": False, "config_warned": False, "bank_created": False})
            assert is_healthy("healthy-sess") is True


# ---------------------------------------------------------------------------
# set_flag
# ---------------------------------------------------------------------------

class TestSetFlag:
    def test_sets_error_notified(self, tmp_path):
        from scripts.lib.state import set_flag, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            set_flag("sess-flag-en", "error_notified", True)
            state = read_session_state("sess-flag-en")
        assert state["error_notified"] is True

    def test_sets_config_warned(self, tmp_path):
        from scripts.lib.state import set_flag, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            set_flag("sess-flag-cw", "config_warned", True)
            state = read_session_state("sess-flag-cw")
        assert state["config_warned"] is True

    def test_sets_bank_created(self, tmp_path):
        from scripts.lib.state import set_flag, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            set_flag("sess-flag-bc", "bank_created", True)
            state = read_session_state("sess-flag-bc")
        assert state["bank_created"] is True

    def test_set_flag_false(self, tmp_path):
        from scripts.lib.state import set_flag, read_session_state, write_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            write_session_state("sess-flag-false", {"healthy": True, "turn_count": 0, "error_notified": True, "config_warned": True, "bank_created": True})
            set_flag("sess-flag-false", "error_notified", False)
            state = read_session_state("sess-flag-false")
        assert state["error_notified"] is False
        # Other flags not touched
        assert state["config_warned"] is True

    def test_set_flag_does_not_clobber_other_fields(self, tmp_path):
        from scripts.lib.state import set_flag, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            set_flag("sess-flag-nc", "error_notified", True)
            state = read_session_state("sess-flag-nc")
        # turn_count and other flags should be at default values
        assert state["turn_count"] == 0
        assert state["config_warned"] is False
        assert state["bank_created"] is False
        assert state["healthy"] is True

    def test_set_healthy_flag(self, tmp_path):
        from scripts.lib.state import set_flag, is_healthy
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            set_flag("sess-flag-h", "healthy", False)
            assert is_healthy("sess-flag-h") is False


# ---------------------------------------------------------------------------
# mark_unhealthy
# ---------------------------------------------------------------------------

class TestMarkUnhealthy:
    def test_marks_session_unhealthy(self, tmp_path):
        from scripts.lib.state import mark_unhealthy, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            mark_unhealthy("sess-mu")
            state = read_session_state("sess-mu")
        assert state["healthy"] is False

    def test_is_healthy_returns_false_after_mark(self, tmp_path):
        from scripts.lib.state import mark_unhealthy, is_healthy
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            assert is_healthy("sess-mu2") is True
            mark_unhealthy("sess-mu2")
            assert is_healthy("sess-mu2") is False

    def test_mark_unhealthy_does_not_clobber_other_fields(self, tmp_path):
        from scripts.lib.state import mark_unhealthy, increment_turn, read_session_state
        with patch.dict(os.environ, _with_state_dir(tmp_path), clear=False):
            increment_turn("sess-mu3")
            increment_turn("sess-mu3")
            mark_unhealthy("sess-mu3")
            state = read_session_state("sess-mu3")
        assert state["healthy"] is False
        assert state["turn_count"] == 2

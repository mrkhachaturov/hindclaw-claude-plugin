import json
import os
import tempfile
import pytest
from unittest.mock import patch

from scripts.lib.config import load_config, debug_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(directory: str, rel: str, data: dict) -> str:
    """Write a JSON file at directory/rel, creating parent dirs."""
    path = os.path.join(directory, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# Layer merge priority tests
# ---------------------------------------------------------------------------

class TestLayerMergePriority:
    """Layer 1 (env) > Layer 2 (project) > Layer 3 (user) > Layer 4 (defaults)."""

    def test_defaults_are_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
                "autoRecall": True,
                "debug": False,
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                with patch.dict(os.environ, {"HINDCLAW_API_URL": "", "HINDCLAW_API_KEY": ""}, clear=False):
                    os.environ.pop("HINDCLAW_API_URL", None)
                    os.environ.pop("HINDCLAW_API_KEY", None)
                    with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                        config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://default.example.com"
            assert config["autoRecall"] is True

    def test_user_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
                "debug": False,
            })

            home_dir = os.path.join(tmp, "home")
            _write_json(tmp, "home/.claude/hindclaw.json", {
                "hindsightApiUrl": "http://user.example.com",
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://user.example.com"

    def test_project_config_overrides_user_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            home_dir = os.path.join(tmp, "home")
            _write_json(tmp, "home/.claude/hindclaw.json", {
                "hindsightApiUrl": "http://user.example.com",
            })

            project_dir = os.path.join(tmp, "project")
            _write_json(tmp, "project/.claude/hindclaw.json", {
                "hindsightApiUrl": "http://project.example.com",
            })

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://project.example.com"

    def test_env_api_url_overrides_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            project_dir = os.path.join(tmp, "project")
            _write_json(tmp, "project/.claude/hindclaw.json", {
                "hindsightApiUrl": "http://project.example.com",
            })

            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {
                "CLAUDE_PLUGIN_ROOT": plugin_root,
                "HINDCLAW_API_URL": "http://env.example.com",
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://env.example.com"

    def test_env_api_key_overrides_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "apiKey": "default-key",
            })

            project_dir = os.path.join(tmp, "project")
            _write_json(tmp, "project/.claude/hindclaw.json", {
                "apiKey": "project-key",
            })

            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {
                "CLAUDE_PLUGIN_ROOT": plugin_root,
                "HINDCLAW_API_KEY": "env-key",
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["apiKey"] == "env-key"

    def test_all_four_layers_stack_correctly(self):
        """Verify all 4 layers contribute distinct keys that don't override each other."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "fromDefaults": "defaults",
                "shared": "from-defaults",
            })

            home_dir = os.path.join(tmp, "home")
            _write_json(tmp, "home/.claude/hindclaw.json", {
                "fromUser": "user",
                "shared": "from-user",
            })

            project_dir = os.path.join(tmp, "project")
            _write_json(tmp, "project/.claude/hindclaw.json", {
                "fromProject": "project",
                "shared": "from-project",
            })

            env = {
                "CLAUDE_PLUGIN_ROOT": plugin_root,
                "HINDCLAW_API_URL": "http://env.example.com",
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            # Each layer contributes its unique key
            assert config["fromDefaults"] == "defaults"
            assert config["fromUser"] == "user"
            assert config["fromProject"] == "project"
            assert config["hindsightApiUrl"] == "http://env.example.com"
            # Highest priority wins for the shared key
            assert config["shared"] == "from-project"


# ---------------------------------------------------------------------------
# No auto-derivation tests
# ---------------------------------------------------------------------------

class TestNoAutoDerivation:
    """Verify no userId, agentName, bankIdPrefix, or bankId are auto-derived."""

    def test_no_userId_in_result_when_not_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {"hindsightApiUrl": "http://x.com"})

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            # userId must NOT be auto-injected
            assert "userId" not in config

    def test_no_agentName_in_result_when_not_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {"hindsightApiUrl": "http://x.com"})

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert "agentName" not in config

    def test_no_bankId_derived_when_not_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://x.com",
                "bankIdPrefix": "someprefix",
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            # bankId must NOT be auto-derived from prefix + agent
            assert "bankId" not in config

    def test_bankId_passthrough_when_explicit_in_config(self):
        """Explicit bankId in config passes through unchanged — no derivation."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "bankId": "explicit::bank",
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["bankId"] == "explicit::bank"

    def test_no_subprocess_called(self):
        """load_config must not call any subprocess (no git commands)."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {"hindsightApiUrl": "http://x.com"})

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    with patch("subprocess.run") as mock_run:
                        load_config({"cwd": project_dir})
                        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Env variable override tests
# ---------------------------------------------------------------------------

class TestEnvVarOverrides:
    """Env vars HINDCLAW_API_URL and HINDCLAW_API_KEY override everything."""

    def test_api_url_env_sets_hindsightApiUrl(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"HINDCLAW_API_URL": "http://from-env.example.com"}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_KEY", None)
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://from-env.example.com"

    def test_api_key_env_sets_apiKey(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"HINDCLAW_API_KEY": "secret-from-env"}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["apiKey"] == "secret-from-env"

    def test_empty_env_vars_do_not_override(self):
        """Empty string env vars must not overwrite config values."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://from-settings.example.com",
                "apiKey": "settings-key",
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            # Env vars present but empty — should not override
            env = {
                "CLAUDE_PLUGIN_ROOT": plugin_root,
                "HINDCLAW_API_URL": "",
                "HINDCLAW_API_KEY": "",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://from-settings.example.com"
            assert config["apiKey"] == "settings-key"


# ---------------------------------------------------------------------------
# Missing config files handled gracefully
# ---------------------------------------------------------------------------

class TestMissingFiles:
    def test_missing_plugin_settings_returns_partial_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            # CLAUDE_PLUGIN_ROOT points to non-existent dir
            env = {"CLAUDE_PLUGIN_ROOT": os.path.join(tmp, "no-such-plugin")}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            # Should succeed with empty config, not raise
            assert isinstance(config, dict)

    def test_missing_user_config_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            project_dir = os.path.join(tmp, "project")
            os.makedirs(project_dir)
            # home_dir has no .claude/hindclaw.json
            home_dir = os.path.join(tmp, "home-empty")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://default.example.com"

    def test_missing_project_config_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            # project dir has no .claude/hindclaw.json
            project_dir = os.path.join(tmp, "project-no-config")
            os.makedirs(project_dir)
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            assert config["hindsightApiUrl"] == "http://default.example.com"

    def test_invalid_json_in_project_config_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            project_dir = os.path.join(tmp, "project")
            claude_dir = os.path.join(project_dir, ".claude")
            os.makedirs(claude_dir)
            with open(os.path.join(claude_dir, "hindclaw.json"), "w") as f:
                f.write("not valid json {{{")

            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": project_dir})

            # Falls back to plugin defaults, does not raise
            assert config["hindsightApiUrl"] == "http://default.example.com"

    def test_empty_cwd_skips_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = os.path.join(tmp, "plugin")
            os.makedirs(plugin_root)
            _write_json(tmp, "plugin/settings.json", {
                "hindsightApiUrl": "http://default.example.com",
            })

            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({"cwd": ""})

            assert config["hindsightApiUrl"] == "http://default.example.com"

    def test_missing_cwd_key_handled_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_dir = os.path.join(tmp, "home")
            os.makedirs(home_dir)

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HINDCLAW_API_URL", None)
                os.environ.pop("HINDCLAW_API_KEY", None)
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
                with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                    config = load_config({})

            assert isinstance(config, dict)


# ---------------------------------------------------------------------------
# debug_log function tests
# ---------------------------------------------------------------------------

class TestDebugLog:
    def test_debug_log_writes_to_stderr_when_debug_true(self, capsys):
        config = {"debug": True}
        debug_log(config, "test message", "extra")

        captured = capsys.readouterr()
        assert "test message" in captured.err
        assert "extra" in captured.err
        assert "[hindclaw]" in captured.err

    def test_debug_log_silent_when_debug_false(self, capsys):
        config = {"debug": False}
        debug_log(config, "should not appear")

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_debug_log_silent_when_debug_missing(self, capsys):
        config = {}
        debug_log(config, "should not appear")

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_debug_log_handles_multiple_args(self, capsys):
        config = {"debug": True}
        debug_log(config, "arg1", "arg2", "arg3")

        captured = capsys.readouterr()
        assert "arg1" in captured.err
        assert "arg2" in captured.err
        assert "arg3" in captured.err


# ---------------------------------------------------------------------------
# _load_json edge cases
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_load_json_returns_empty_dict_for_missing_file(self):
        from scripts.lib.config import _load_json
        result = _load_json("/nonexistent/path/file.json")
        assert result == {}

    def test_load_json_returns_empty_dict_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            from scripts.lib.config import _load_json
            bad_file = os.path.join(tmp, "bad.json")
            with open(bad_file, "w") as f:
                f.write("not json {{{")
            result = _load_json(bad_file)
            assert result == {}

    def test_load_json_returns_data_for_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            from scripts.lib.config import _load_json
            good_file = os.path.join(tmp, "good.json")
            data = {"key": "value", "num": 42}
            with open(good_file, "w") as f:
                json.dump(data, f)
            result = _load_json(good_file)
            assert result == data

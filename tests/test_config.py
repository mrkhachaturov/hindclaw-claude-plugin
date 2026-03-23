import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(tmp_path, rel, data):
    """Write a JSON file at tmp_path / rel, creating parent dirs."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return str(p)


# ---------------------------------------------------------------------------
# Layer merge priority tests
# ---------------------------------------------------------------------------

class TestLayerMergePriority:
    """Layer 1 (env) > Layer 2 (project) > Layer 3 (user) > Layer 4 (defaults)."""

    def test_defaults_are_base(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        settings = {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "autoRecall": True,
            "debug": False,
        }
        _write_json(tmp_path, "plugin/settings.json", settings)

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://default.example.com"
        assert config["clientId"] == "claude-code"

    def test_user_config_overrides_defaults(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        })

        home_dir = str(tmp_path / "home")
        os.makedirs(home_dir + "/.claude", exist_ok=True)
        _write_json(tmp_path, "home/.claude/hindclaw.json", {
            "hindsightApiUrl": "http://user.example.com",
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stdout="")
                    config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://user.example.com"

    def test_project_config_overrides_user_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        })

        home_dir = str(tmp_path / "home")
        os.makedirs(home_dir + "/.claude", exist_ok=True)
        _write_json(tmp_path, "home/.claude/hindclaw.json", {
            "hindsightApiUrl": "http://user.example.com",
        })

        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir + "/.claude", exist_ok=True)
        _write_json(tmp_path, "project/.claude/hindclaw.json", {
            "hindsightApiUrl": "http://project.example.com",
        })

        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stdout="")
                    config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://project.example.com"

    def test_env_var_overrides_project_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        })

        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir + "/.claude", exist_ok=True)
        _write_json(tmp_path, "project/.claude/hindclaw.json", {
            "hindsightApiUrl": "http://project.example.com",
        })

        hook_input = {"cwd": project_dir}

        env = {
            "CLAUDE_PLUGIN_ROOT": plugin_root,
            "HINDCLAW_API_URL": "http://env.example.com",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://env.example.com"

    def test_env_user_id_overrides_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "from-settings@example.com",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {
            "CLAUDE_PLUGIN_ROOT": plugin_root,
            "HINDCLAW_USER_ID": "from-env@example.com",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["userId"] == "from-env@example.com"

    def test_env_jwt_secret_overrides_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "user@example.com",
            "jwtSecret": "settings-secret",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {
            "CLAUDE_PLUGIN_ROOT": plugin_root,
            "HINDCLAW_JWT_SECRET": "env-secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["jwtSecret"] == "env-secret"

    def test_missing_user_config_is_skipped_gracefully(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        })

        home_dir = str(tmp_path / "home-no-config")
        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", home_dir)):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stdout="")
                    config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://default.example.com"

    def test_missing_project_config_is_skipped_gracefully(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "http://default.example.com",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        })

        project_dir = str(tmp_path / "project-no-claude-dir")
        os.makedirs(project_dir, exist_ok=True)

        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["hindsightApiUrl"] == "http://default.example.com"


# ---------------------------------------------------------------------------
# User ID resolution tests
# ---------------------------------------------------------------------------

class TestResolveUserId:
    def _make_config(self, tmp_path, plugin_root_data=None, project_data=None, env=None):
        """Helper to call load_config with controlled layers."""
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        defaults = {
            "hindsightApiUrl": "",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        }
        if plugin_root_data:
            defaults.update(plugin_root_data)
        _write_json(tmp_path, "plugin/settings.json", defaults)

        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir + "/.claude", exist_ok=True)
        if project_data:
            _write_json(tmp_path, "project/.claude/hindclaw.json", project_data)

        hook_input = {"cwd": project_dir}
        base_env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
        if env:
            base_env.update(env)

        # Remove any HINDCLAW_* vars that could bleed from the real environment
        remove_keys = ["HINDCLAW_API_URL", "HINDCLAW_USER_ID", "HINDCLAW_JWT_SECRET"]
        with patch.dict(os.environ, base_env, clear=False):
            for k in remove_keys:
                os.environ.pop(k, None)
            yield load_config, hook_input

    def test_user_id_from_env_var(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {"CLAUDE_PLUGIN_ROOT": plugin_root, "HINDCLAW_USER_ID": "env-user@example.com"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HINDCLAW_API_URL", None)
            os.environ.pop("HINDCLAW_JWT_SECRET", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["userId"] == "env-user@example.com"

    def test_user_id_from_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "settings-user@example.com",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["userId"] == "settings-user@example.com"

    def test_user_id_falls_back_to_git_config(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {"CLAUDE_PLUGIN_ROOT": plugin_root}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            if cmd == ["git", "config", "user.email"]:
                result.returncode = 0
                result.stdout = "git-user@example.com\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["userId"] == "git-user@example.com"

    def test_user_id_empty_when_git_config_fails(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        _write_json(tmp_path, "plugin/settings.json", {
            "hindsightApiUrl": "",
            "userId": "",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "prefix",
            "agentName": "agent",
            "bankId": "",
            "debug": False,
        })

        hook_input = {"cwd": str(tmp_path / "project")}
        os.makedirs(str(tmp_path / "project"), exist_ok=True)

        env = {"CLAUDE_PLUGIN_ROOT": plugin_root}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["userId"] == ""


# ---------------------------------------------------------------------------
# Agent name resolution tests
# ---------------------------------------------------------------------------

class TestResolveAgentName:
    def _base_settings(self, tmp_path, extra=None):
        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        data = {
            "hindsightApiUrl": "",
            "userId": "user@example.com",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "user_example_com",
            "agentName": "",
            "bankId": "",
            "debug": False,
        }
        if extra:
            data.update(extra)
        _write_json(tmp_path, "plugin/settings.json", data)
        return plugin_root

    def test_explicit_agent_name_wins(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {"agentName": "explicit-agent"})
        project_dir = str(tmp_path / "my-project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["agentName"] == "explicit-agent"

    def test_agent_name_from_git_remote_https(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path)
        project_dir = str(tmp_path / "my-project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            if cmd == ["git", "-C", project_dir, "remote", "get-url", "origin"]:
                result.returncode = 0
                result.stdout = "https://github.com/user/astromech.git\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["agentName"] == "astromech"

    def test_agent_name_from_git_remote_ssh(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path)
        project_dir = str(tmp_path / "my-project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            if cmd == ["git", "-C", project_dir, "remote", "get-url", "origin"]:
                result.returncode = 0
                result.stdout = "git@github.com:user/my-repo.git\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["agentName"] == "my-repo"

    def test_agent_name_strips_dot_git_suffix(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path)
        project_dir = str(tmp_path / "my-project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            if cmd == ["git", "-C", project_dir, "remote", "get-url", "origin"]:
                result.returncode = 0
                result.stdout = "https://github.com/org/repo-name.git\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["agentName"] == "repo-name"

    def test_agent_name_fallback_to_folder_basename(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path)
        project_dir = str(tmp_path / "my-special-project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["agentName"] == "my-special-project"

    def test_agent_name_from_project_config_explicit(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path)
        project_dir = str(tmp_path / "my-project")
        os.makedirs(project_dir + "/.claude")
        _write_json(tmp_path, "my-project/.claude/hindclaw.json", {"agentName": "project-agent"})
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["agentName"] == "project-agent"


# ---------------------------------------------------------------------------
# Bank ID derivation tests
# ---------------------------------------------------------------------------

class TestDeriveBankId:
    def _base_settings(self, tmp_path, extra=None):
        plugin_root = str(tmp_path / "plugin")
        os.makedirs(plugin_root)
        data = {
            "hindsightApiUrl": "",
            "userId": "user@example.com",
            "jwtSecret": "",
            "clientId": "claude-code",
            "bankIdPrefix": "",
            "agentName": "",
            "bankId": "",
            "debug": False,
        }
        if extra:
            data.update(extra)
        _write_json(tmp_path, "plugin/settings.json", data)
        return plugin_root

    def test_explicit_bank_id_skips_derivation(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "bankId": "custom::bank",
            "agentName": "ignored",
            "bankIdPrefix": "ignored",
        })
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["bankId"] == "custom::bank"

    def test_bank_id_derived_from_prefix_and_agent(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "bankIdPrefix": "myprefix",
            "agentName": "myagent",
        })
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["bankId"] == "myprefix::myagent"

    def test_bank_id_auto_prefix_from_email(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "userId": "ceo@astrateam.net",
            "agentName": "astromech",
        })
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            return result

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["bankId"] == "ceo_astrateam_net::astromech"

    def test_bank_id_auto_prefix_replaces_at_and_dot(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "userId": "john.doe@my.company.io",
            "agentName": "myproject",
        })
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["bankId"] == "john_doe_my_company_io::myproject"

    def test_bank_id_uses_git_remote_for_agent_name(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "userId": "ceo@astrateam.net",
        })
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock()
            if cmd == ["git", "-C", project_dir, "remote", "get-url", "origin"]:
                result.returncode = 0
                result.stdout = "https://github.com/user/astromech.git\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                config = load_config(hook_input)

        assert config["bankId"] == "ceo_astrateam_net::astromech"

    def test_bank_id_uses_folder_fallback_for_agent_name(self, tmp_path):
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {
            "userId": "user@example.com",
            "bankIdPrefix": "myprefix",
        })
        project_dir = str(tmp_path / "my-special-folder")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        assert config["bankId"] == "myprefix::my-special-folder"

    def test_bank_id_empty_when_no_agent_and_no_user(self, tmp_path):
        """If userId is empty and no prefix, bankId should be empty or gracefully handled."""
        from scripts.lib.config import load_config

        plugin_root = self._base_settings(tmp_path, {"userId": ""})
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        hook_input = {"cwd": project_dir}

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": plugin_root}, clear=False):
            os.environ.pop("HINDCLAW_USER_ID", None)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                config = load_config(hook_input)

        # userId is empty, so auto-prefix from email is empty → bankId should be empty
        assert config["bankId"] == ""


# ---------------------------------------------------------------------------
# debug_log function tests
# ---------------------------------------------------------------------------

class TestDebugLog:
    def test_debug_log_writes_to_stderr_when_debug_true(self, capsys):
        from scripts.lib.config import debug_log

        config = {"debug": True}
        debug_log(config, "test message", "extra")

        captured = capsys.readouterr()
        assert "test message" in captured.err
        assert "extra" in captured.err

    def test_debug_log_silent_when_debug_false(self, capsys):
        from scripts.lib.config import debug_log

        config = {"debug": False}
        debug_log(config, "should not appear")

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_debug_log_silent_when_debug_missing(self, capsys):
        from scripts.lib.config import debug_log

        config = {}
        debug_log(config, "should not appear")

        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# _load_json edge cases
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_load_json_returns_empty_dict_for_missing_file(self):
        from scripts.lib.config import _load_json
        result = _load_json("/nonexistent/path/file.json")
        assert result == {}

    def test_load_json_returns_empty_dict_for_invalid_json(self, tmp_path):
        from scripts.lib.config import _load_json
        bad_file = str(tmp_path / "bad.json")
        with open(bad_file, "w") as f:
            f.write("not json {{{")
        result = _load_json(bad_file)
        assert result == {}

    def test_load_json_returns_data_for_valid_file(self, tmp_path):
        from scripts.lib.config import _load_json
        good_file = str(tmp_path / "good.json")
        data = {"key": "value", "num": 42}
        with open(good_file, "w") as f:
            json.dump(data, f)
        result = _load_json(good_file)
        assert result == data

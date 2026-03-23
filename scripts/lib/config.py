"""Layered config loading for the HindClaw Claude Code plugin.

Merges four configuration layers (highest priority wins):
  1. Environment variables (HINDCLAW_API_URL, HINDCLAW_USER_ID, HINDCLAW_JWT_SECRET)
  2. Project config (``.claude/hindclaw.json`` in project root)
  3. User config (``~/.claude/hindclaw.json``)
  4. Plugin defaults (``settings.json`` in ``$CLAUDE_PLUGIN_ROOT``)

After merging, auto-resolves userId (git email fallback), agentName
(git remote / folder basename), and bankId (``{prefix}::{agent}``).
"""

import json
import os
import subprocess
import sys


def _load_json(path: str) -> dict:
    """Load a JSON file, returning an empty dict on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def debug_log(config: dict, *args) -> None:
    """Log to stderr if debug is enabled in config."""
    if config.get("debug"):
        print("[hindclaw]", *args, file=sys.stderr)


def _resolve_user_id(config: dict) -> str:
    """Resolve userId: env var → config value → git config fallback.

    Args:
        config: Merged config dict (env vars already applied at layer 1).

    Returns:
        Resolved user ID string, or empty string if not found.
    """
    # Layer 1 (env) is already in config by the time this is called.
    # If it's set (non-empty), return it.
    value = config.get("userId", "")
    if value:
        return value

    # Fall back to git config user.email
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            email = result.stdout.strip()
            if email:
                return email
    except Exception:
        pass

    return ""


def _resolve_agent_name(cwd: str, config: dict) -> str:
    """Resolve agentName: explicit config → git remote → folder basename.

    Args:
        cwd: The project root directory (from hook_input).
        config: Merged config dict (all layers already applied).

    Returns:
        Resolved agent name string.
    """
    explicit = config.get("agentName", "")
    if explicit:
        return explicit

    # Try git remote URL
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            if url:
                # Extract repo name from URL, stripping .git suffix
                # Works for both HTTPS (https://github.com/user/repo.git)
                # and SSH (git@github.com:user/repo.git)
                repo = url.rstrip("/")
                # Take the last path segment
                repo = repo.split("/")[-1]
                # For SSH URLs like git@github.com:user/repo.git, the last part
                # after split('/') already gives 'repo.git'
                # But for ssh with colon: git@github.com:user/repo → split(':')[-1].split('/')[-1]
                if ":" in url and not url.startswith("http"):
                    # SSH format: git@host:user/repo.git
                    repo = url.split(":")[-1]
                    repo = repo.split("/")[-1]
                if repo.endswith(".git"):
                    repo = repo[:-4]
                if repo:
                    return repo
    except Exception:
        pass

    # Fallback: folder basename
    return os.path.basename(cwd)


def _derive_bank_id(config: dict) -> str:
    """Derive bankId from prefix and agent name.

    Args:
        config: Config dict with resolved userId, agentName, bankIdPrefix, bankId.

    Returns:
        Derived bank ID string, or empty string if insufficient data.
    """
    # Explicit override — skip all derivation
    explicit = config.get("bankId", "")
    if explicit:
        return explicit

    agent = config.get("agentName", "")
    prefix = config.get("bankIdPrefix", "")

    # Auto-prefix from userId (email → replace @ and . with _)
    if not prefix:
        user_id = config.get("userId", "")
        if user_id:
            prefix = user_id.replace("@", "_").replace(".", "_")

    if not prefix or not agent:
        return ""

    return f"{prefix}::{agent}"


def load_config(hook_input: dict) -> dict:
    """Load and merge the 4-layer config.

    Layers (highest priority wins):
      1. Environment variables (HINDCLAW_API_URL, HINDCLAW_USER_ID, HINDCLAW_JWT_SECRET)
      2. Project config (.claude/hindclaw.json in cwd)
      3. User config (~/.claude/hindclaw.json)
      4. Plugin defaults (settings.json in $CLAUDE_PLUGIN_ROOT)

    Args:
        hook_input: Claude Code hook input dict, must contain 'cwd'.

    Returns:
        Merged config dict with resolved auto fields (userId, agentName, bankId).
    """
    cwd = hook_input.get("cwd", "")

    # --- Layer 4: Plugin defaults ---
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    settings_path = os.path.join(plugin_root, "settings.json") if plugin_root else ""
    config = _load_json(settings_path) if settings_path else {}

    # --- Layer 3: User config ---
    user_config_path = os.path.join(os.path.expanduser("~"), ".claude", "hindclaw.json")
    user_config = _load_json(user_config_path)
    config.update(user_config)

    # --- Layer 2: Project config ---
    if cwd:
        project_config_path = os.path.join(cwd, ".claude", "hindclaw.json")
        project_config = _load_json(project_config_path)
        config.update(project_config)

    # --- Layer 1: Environment variables ---
    env_api_url = os.environ.get("HINDCLAW_API_URL", "")
    if env_api_url:
        config["hindsightApiUrl"] = env_api_url

    env_user_id = os.environ.get("HINDCLAW_USER_ID", "")
    if env_user_id:
        config["userId"] = env_user_id

    env_jwt_secret = os.environ.get("HINDCLAW_JWT_SECRET", "")
    if env_jwt_secret:
        config["jwtSecret"] = env_jwt_secret

    # --- Resolve auto fields ---
    config["userId"] = _resolve_user_id(config)
    config["agentName"] = _resolve_agent_name(cwd, config)
    config["bankId"] = _derive_bank_id(config)

    return config

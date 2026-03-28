"""Layered config loading for the HindClaw Claude Code plugin.

Merges four configuration layers (highest priority wins):
  1. Environment variables (HINDCLAW_API_URL, HINDCLAW_API_KEY)
  2. Project config (``.claude/hindclaw.json`` in project root)
  3. User config (``~/.claude/hindclaw.json``)
  4. Plugin defaults (``settings.json`` in ``$CLAUDE_PLUGIN_ROOT``)

No auto-derivation. Bank IDs, API keys, and server URLs are explicit.
"""

import json
import os
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


def load_config(hook_input: dict) -> dict:
    """Load and merge config layers. No auto-derivation.

    Args:
        hook_input: Claude Code hook input dict, must contain 'cwd'.

    Returns:
        Merged config dict.
    """
    cwd = hook_input.get("cwd", "")

    # Layer 4: Plugin defaults
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    settings_path = os.path.join(plugin_root, "settings.json") if plugin_root else ""
    config = _load_json(settings_path) if settings_path else {}

    # Layer 3: User config
    user_config_path = os.path.join(os.path.expanduser("~"), ".claude", "hindclaw.json")
    user_config = _load_json(user_config_path)
    config.update(user_config)

    # Layer 2: Project config
    if cwd:
        project_config_path = os.path.join(cwd, ".claude", "hindclaw.json")
        project_config = _load_json(project_config_path)
        config.update(project_config)

    # Layer 1: Environment variables
    env_api_url = os.environ.get("HINDCLAW_API_URL", "")
    if env_api_url:
        config["hindsightApiUrl"] = env_api_url

    env_api_key = os.environ.get("HINDCLAW_API_KEY", "")
    if env_api_key:
        config["apiKey"] = env_api_key

    return config

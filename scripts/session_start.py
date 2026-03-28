"""SessionStart hook — health check and init state.

Validates config, checks server reachability, writes initial session state.
Outputs systemMessage on failure so the user sees it in their terminal.
"""

import json
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_scripts_dir)
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _project_root)

from lib.client import HindclawClient  # noqa: E402
from lib.config import debug_log, load_config  # noqa: E402
from lib.state import write_session_state  # noqa: E402


def main() -> None:
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")
    config = load_config(hook_input)
    debug_log(config, "session_start: loaded config for session", session_id)

    api_url = config.get("hindsightApiUrl", "")
    api_key = config.get("apiKey", "")
    bank_id = config.get("bankId", "")

    initial_state = {
        "healthy": False,
        "turn_count": 0,
        "error_notified": False,
        "config_warned": False,
        "bank_created": False,
    }

    # Validate required config
    missing = []
    if not api_url:
        missing.append("hindsightApiUrl")
    if not api_key:
        missing.append("apiKey")
    if not bank_id:
        missing.append("bankId")

    if missing:
        write_session_state(session_id, initial_state)
        output = {
            "systemMessage": f"HindClaw plugin: missing required config: {', '.join(missing)}",
        }
        json.dump(output, sys.stdout)
        return

    client = HindclawClient(api_url=api_url, api_key=api_key)
    healthy = client.health_check()

    initial_state["healthy"] = healthy
    write_session_state(session_id, initial_state)

    if healthy:
        debug_log(config, f"session_start: connected to {api_url}")
    else:
        output = {
            "systemMessage": f"HindClaw plugin: cannot reach Hindsight server at {api_url}",
        }
        json.dump(output, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[HindClaw] session_start error: {exc}", file=sys.stderr)
        if os.environ.get("HINDCLAW_DEBUG"):
            sys.exit(2)
    sys.exit(0)

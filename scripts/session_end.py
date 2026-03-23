"""SessionEnd hook — clean up per-session state on session close.

Flow:
  1. Read hook input JSON from stdin (contains session_id).
  2. Call state.delete_session_state(session_id) to remove the state file.
  3. Exit 0.
"""

import json
import os
import sys

# Add the scripts directory to sys.path so lib.* imports resolve correctly.
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_scripts_dir)
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _project_root)

from lib.state import delete_session_state  # noqa: E402


def main() -> None:
    """Run the SessionEnd hook.

    Reads hook input from stdin and deletes the per-session state file.
    No-op if the state file does not exist.

    Exits 0 in all cases.
    """
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")
    delete_session_state(session_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[HindClaw] session_end error: {exc}", file=sys.stderr)
        if os.environ.get("HINDCLAW_DEBUG"):
            sys.exit(2)
    sys.exit(0)

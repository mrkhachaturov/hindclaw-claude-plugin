"""SessionStart hook — connect to Hindsight and write initial session state.

Flow:
  1. Read hook input JSON from stdin (contains session_id, cwd).
  2. Load the merged 4-layer config via config.load_config().
  3. Validate that hindsightApiUrl and jwtSecret are present.
  4. Build a HindclawClient with a claims_builder closure.
  5. Run a health check against the Hindsight API.
  6. Write session state: {"healthy": True/False, "denied_banks": [], "turn_count": 0}.
  7. Log the result to stderr.
  8. Exit 0 always (graceful degradation — never block a session).
"""

import json
import os
import sys

# Add the scripts directory to sys.path so lib.* imports resolve correctly.
# Also add the project root so client.py's internal `from scripts.lib.*` works.
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_scripts_dir)
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _project_root)

from lib.auth import build_claims  # noqa: E402
from lib.client import HindclawClient  # noqa: E402
from lib.config import debug_log, load_config  # noqa: E402
from lib.state import write_session_state  # noqa: E402


def make_claims_builder(config: dict, hook_input: dict):
    """Return a closure that builds JWT claims for this session.

    Args:
        config: Merged plugin config with userId, agentName, clientId.
        hook_input: Claude Code hook input with session_id.

    Returns:
        Callable that returns a fresh claims dict each time it is called.
    """
    def claims_builder() -> dict:
        return build_claims(config, hook_input)
    return claims_builder


def main() -> None:
    """Run the SessionStart hook.

    Reads hook input from stdin, loads config, performs a health check against
    the Hindsight API, and writes the initial session state file.

    Exits 0 in all cases to avoid blocking the Claude Code session.
    """
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    config = load_config(hook_input)
    debug_log(config, "session_start: loaded config for session", session_id)

    api_url = config.get("hindsightApiUrl", "")
    jwt_secret = config.get("jwtSecret", "")

    if not api_url or not jwt_secret:
        missing = []
        if not api_url:
            missing.append("hindsightApiUrl")
        if not jwt_secret:
            missing.append("jwtSecret")
        print(
            f"[HindClaw] Missing required config: {', '.join(missing)}",
            file=sys.stderr,
        )
        write_session_state(session_id, {"healthy": False, "denied_banks": [], "turn_count": 0})
        return

    client = HindclawClient(
        api_url=api_url,
        jwt_secret=jwt_secret,
        claims_builder=make_claims_builder(config, hook_input),
    )

    healthy = client.health_check()

    write_session_state(
        session_id,
        {"healthy": healthy, "denied_banks": [], "turn_count": 0},
    )

    if healthy:
        print(f"[HindClaw] Connected to {api_url}", file=sys.stderr)
    else:
        print(f"[HindClaw] Server unreachable at {api_url}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[HindClaw] session_start error: {exc}", file=sys.stderr)
        if os.environ.get("HINDCLAW_DEBUG"):
            sys.exit(2)
    sys.exit(0)

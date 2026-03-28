"""Per-session file-based state persistence.

Claude Code hooks are ephemeral processes — state must be persisted to files.
Each session gets its own JSON file at ``$CLAUDE_PLUGIN_DATA/state/{session_id}.json``.
Concurrent sessions (different projects, terminals) never interfere.

Uses ``fcntl.flock`` for cross-process locking and ``threading.Lock`` for
same-process thread safety during atomic state mutations.
"""

import fcntl
import json
import os
import re
import threading

# Per-process thread lock — guards against concurrent threads in the same process.
# fcntl.flock handles cross-process locking (different Claude Code hook invocations).
_thread_lock = threading.Lock()


def _default_state() -> dict:
    """Return a fresh default session state dict."""
    return {
        "healthy": True,
        "turn_count": 0,
        "error_notified": False,
        "config_warned": False,
        "bank_created": False,
    }


def _state_dir() -> str:
    """Get or create the state directory.

    Uses $CLAUDE_PLUGIN_DATA/state/, falling back to
    ~/.claude/plugins/data/hindclaw-claude-code/state/ when the env var is unset.

    Returns:
        Absolute path to the (created) state directory.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not plugin_data:
        plugin_data = os.path.join(
            os.path.expanduser("~"),
            ".claude", "plugins", "data", "hindclaw-claude-code",
        )
    state_dir = os.path.join(plugin_data, "state")
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def _safe_filename(name: str) -> str:
    """Sanitize a session ID so it is safe to use as a filename.

    Strips path separators, forbidden characters, double-dots, and control
    characters.  Caps the result at 200 characters.

    Args:
        name: Raw session identifier.

    Returns:
        Sanitized filename-safe string, or "state" for empty input.
    """
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = name.replace("..", "_")
    name = name[:200]
    return name or "state"


def _state_file(session_id: str) -> str:
    """Return the absolute path for a session state file.

    Applies path traversal guard: the resolved path must stay inside the state
    directory.

    Args:
        session_id: Session identifier.

    Returns:
        Absolute path to the .json file for this session.

    Raises:
        ValueError: If the resolved path escapes the state directory.
    """
    safe = _safe_filename(session_id)
    state_dir = _state_dir()
    path = os.path.join(state_dir, safe + ".json")
    resolved = os.path.realpath(path)
    expected_dir = os.path.realpath(state_dir)
    if not resolved.startswith(expected_dir + os.sep) and resolved != expected_dir:
        raise ValueError(
            f"State file path escapes state directory: {session_id!r}"
        )
    return path


def read_session_state(session_id: str) -> dict:
    """Read state for a session, returning the default if absent or corrupt.

    Args:
        session_id: Session identifier.

    Returns:
        State dict with keys healthy, turn_count, error_notified, config_warned, bank_created.
    """
    path = _state_file(session_id)
    if not os.path.exists(path):
        return _default_state()
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_state()


def write_session_state(session_id: str, data: dict) -> None:
    """Write state for a session atomically (write-to-.tmp then os.replace).

    Args:
        session_id: Session identifier.
        data: State dict to persist.
    """
    path = _state_file(session_id)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def delete_session_state(session_id: str) -> None:
    """Remove the state file for a session (no-op if it does not exist).

    Called on SessionEnd to clean up per-session state.

    Args:
        session_id: Session identifier.
    """
    path = _state_file(session_id)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def increment_turn(session_id: str) -> int:
    """Atomically increment the turn counter for a session and return the new value.

    Uses both a threading.Lock (same-process threads) and fcntl.flock (cross-process
    concurrent hook invocations) to prevent race conditions.

    Args:
        session_id: Session identifier.

    Returns:
        New turn count after increment.
    """
    path = _state_file(session_id)
    lock_path = path + ".lock"
    with _thread_lock:
        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                state = read_session_state(session_id)
                state["turn_count"] = state.get("turn_count", 0) + 1
                write_session_state(session_id, state)
                return state["turn_count"]
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def set_flag(session_id: str, flag: str, value: bool) -> None:
    """Atomically set a boolean flag in session state.

    Args:
        session_id: Session identifier.
        flag: Flag name (error_notified, config_warned, bank_created).
        value: Boolean value to set.
    """
    path = _state_file(session_id)
    lock_path = path + ".lock"
    with _thread_lock:
        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                state = read_session_state(session_id)
                state[flag] = value
                write_session_state(session_id, state)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def mark_unhealthy(session_id: str) -> None:
    """Mark session as unhealthy. All hooks will skip."""
    set_flag(session_id, "healthy", False)


def is_healthy(session_id: str) -> bool:
    """Return whether the session is currently marked healthy.

    Args:
        session_id: Session identifier.

    Returns:
        True if healthy flag is set (or session not yet seen), False otherwise.
    """
    state = read_session_state(session_id)
    return bool(state.get("healthy", True))



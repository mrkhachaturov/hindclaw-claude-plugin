"""Stop hook — persist a sliding window of conversation turns to Hindsight.

Flow:
  1. Read hook input JSON from stdin (session_id, cwd, transcript_path).
  2. Load config, check guards: autoRetain, healthy, bankId, credentials.
  3. Read full transcript from transcript_path JSONL via read_transcript().
  4. If transcript empty → exit.
  5. Increment turn count via state.increment_turn(session_id).
  6. If turn_count % retainEveryNTurns != 0 → exit (chunked retention).
  7. When retaining: compute sliding window of last
     retainEveryNTurns + retainOverlapTurns turns via
     slice_last_turns_by_user_boundary().
  8. Prepare retention transcript via content.prepare_retention_transcript()
     with role filtering and retain_full_window=True.
  9. If chunk empty → exit.
 10. Create HindclawClient with API key auth.
 11. Build items array: [{"content": transcript_text, "context": retainContext}].
 12. Call client.retain(bank_id, items, async_=True).
 13. On 404 → attempt bank creation from template, then retry retain.
     On 401/403 → mark_unhealthy (user notified on next recall via systemMessage).
     On other error → log to stderr.
 14. Exit (no stdout output — Stop hook is fire-and-forget).
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

from lib.client import HindclawClient, HindclawHttpError  # noqa: E402
from lib.config import debug_log, load_config  # noqa: E402
from lib.content import prepare_retention_transcript, slice_last_turns_by_user_boundary  # noqa: E402
from lib.state import increment_turn, is_healthy, mark_unhealthy, read_session_state, set_flag  # noqa: E402


def read_transcript(transcript_path: str) -> list:
    """Read a JSONL transcript file and return list of message dicts.

    Handles both the nested format used by Claude Code
    (``{"type":"user","message":{"role":"user","content":"..."}}``),
    and a flat format (``{"role":"user","content":"..."}``) defensively.

    Args:
        transcript_path: Absolute path to the JSONL transcript file.

    Returns:
        List of ``{"role": str, "content": str|list}`` dicts in order,
        or an empty list when the file is absent or unparseable.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return []
    messages = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Nested format: {"type": "user"|"assistant", "message": {"role": ..., "content": ...}}
                if entry.get("type") in ("user", "assistant"):
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("role"):
                        messages.append(msg)
                    continue

                # Flat format: {"role": ..., "content": ...}
                if "role" in entry and "content" in entry:
                    messages.append(entry)
    except OSError:
        pass
    return messages


def main() -> None:
    """Run the Stop retain hook.

    Reads hook input from stdin, checks guards, reads the transcript,
    applies chunked-retention logic, and posts the sliding window to
    the Hindsight retain endpoint.

    Exits 0 in all cases to avoid blocking the Claude Code session.
    Produces no stdout output (fire-and-forget Stop hook).
    """
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    config = load_config(hook_input)
    debug_log(config, "retain: loaded config for session", session_id)

    # Guard 1: autoRetain disabled
    if not config.get("autoRetain", True):
        debug_log(config, "retain: autoRetain disabled, skipping")
        return

    # Guard 2: session not healthy
    if not is_healthy(session_id):
        debug_log(config, "retain: session not healthy, skipping")
        return

    # Guard 3: need a bankId
    bank_id = config.get("bankId", "")
    if not bank_id:
        debug_log(config, "retain: no bankId resolved, skipping")
        return

    # Guard 4: need API URL + API key
    api_url = config.get("hindsightApiUrl", "")
    api_key = config.get("apiKey", "")
    if not api_url or not api_key:
        debug_log(config, "retain: missing hindsightApiUrl or apiKey, skipping")
        return

    # Read transcript
    transcript_path = hook_input.get("transcript_path", "")
    all_messages = read_transcript(transcript_path)
    debug_log(config, f"retain: read {len(all_messages)} messages from transcript")

    if not all_messages:
        debug_log(config, "retain: transcript empty, skipping")
        return

    # Increment turn count; skip if not on a retention boundary
    retain_every_n = int(config.get("retainEveryNTurns", 5))
    turn_count = increment_turn(session_id)
    debug_log(config, f"retain: turn_count={turn_count}, retain_every_n={retain_every_n}")

    if retain_every_n > 0 and turn_count % retain_every_n != 0:
        debug_log(config, f"retain: turn {turn_count} not a retention boundary, skipping")
        return

    # Compute sliding window: last (retainEveryNTurns + retainOverlapTurns) turns
    retain_overlap = int(config.get("retainOverlapTurns", 1))
    window_turns = retain_every_n + retain_overlap
    window_messages = slice_last_turns_by_user_boundary(all_messages, window_turns)
    debug_log(config, f"retain: window={window_turns} turns, messages_in_window={len(window_messages)}")

    # Prepare retention transcript
    retain_roles = config.get("retainRoles", ["user", "assistant"])
    transcript_text, part_count = prepare_retention_transcript(
        window_messages,
        retain_roles=retain_roles,
        retain_full_window=True,
    )

    if not transcript_text:
        debug_log(config, "retain: prepared transcript empty, skipping")
        return

    debug_log(config, f"retain: prepared {part_count} parts, len={len(transcript_text)}")

    # Build client
    client = HindclawClient(api_url=api_url, api_key=api_key)

    retain_context = config.get("retainContext", "")
    items = [{"content": transcript_text, "context": retain_context}]

    try:
        client.retain(bank_id, items, async_=True)
        debug_log(config, f"retain: submitted {part_count} parts to bank {bank_id!r}")
    except HindclawHttpError as exc:
        if exc.status_code == 404:
            # Bank doesn't exist — try creating from template
            template = config.get("template")
            state = read_session_state(session_id)
            if not template:
                print(
                    f"[HindClaw] retain: bank {bank_id!r} not found. "
                    f"Set 'template' in config to auto-create.",
                    file=sys.stderr,
                )
                mark_unhealthy(session_id)
                return
            if state.get("bank_created"):
                # Already tried creating this session — don't retry
                print(f"[HindClaw] retain: bank creation already attempted, skipping", file=sys.stderr)
                mark_unhealthy(session_id)
                return
            # Attempt bank creation
            try:
                client.create_bank(bank_id, template)
                set_flag(session_id, "bank_created", True)
                debug_log(config, f"retain: created bank {bank_id!r} from template {template!r}")
                # Retry the retain
                try:
                    client.retain(bank_id, items, async_=True)
                    debug_log(config, f"retain: retry successful for bank {bank_id!r}")
                except Exception as retry_exc:
                    print(f"[HindClaw] retain: retry after bank creation failed: {retry_exc}", file=sys.stderr)
            except HindclawHttpError as create_exc:
                if create_exc.status_code == 409:
                    # Bank already exists (created by another session) — just retry retain
                    set_flag(session_id, "bank_created", True)
                    debug_log(config, f"retain: bank {bank_id!r} already exists (409), retrying retain")
                    try:
                        client.retain(bank_id, items, async_=True)
                        debug_log(config, f"retain: retry successful for bank {bank_id!r}")
                    except Exception as retry_exc:
                        print(f"[HindClaw] retain: retry after 409 failed: {retry_exc}", file=sys.stderr)
                elif create_exc.status_code == 403:
                    print(f"[HindClaw] retain: no permission to create bank (403)", file=sys.stderr)
                    mark_unhealthy(session_id)
                elif create_exc.status_code == 404:
                    print(f"[HindClaw] retain: template {template!r} not found on server", file=sys.stderr)
                    mark_unhealthy(session_id)
                elif create_exc.status_code == 422:
                    print(f"[HindClaw] retain: bank creation validation error: {create_exc.body}", file=sys.stderr)
                    mark_unhealthy(session_id)
                else:
                    print(f"[HindClaw] retain: bank creation failed ({create_exc.status_code}): {create_exc.body}", file=sys.stderr)
                    mark_unhealthy(session_id)
            except Exception as create_exc:
                print(f"[HindClaw] retain: bank creation error: {create_exc}", file=sys.stderr)
                mark_unhealthy(session_id)
            return
        if exc.status_code in (401, 403):
            print(f"[HindClaw] retain: access denied ({exc.status_code}), marking unhealthy", file=sys.stderr)
            mark_unhealthy(session_id)
            return
        print(f"[HindClaw] retain: HTTP error {exc.status_code}: {exc.body}", file=sys.stderr)
        return
    except Exception as exc:
        print(f"[HindClaw] retain: unexpected error: {exc}", file=sys.stderr)
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[HindClaw] retain error: {exc}", file=sys.stderr)
        if os.environ.get("HINDCLAW_DEBUG"):
            sys.exit(2)
    sys.exit(0)

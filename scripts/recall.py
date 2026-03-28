"""UserPromptSubmit hook — recall relevant memories before each prompt.

Flow:
  1. Read hook input JSON from stdin (session_id, cwd, prompt/user_prompt,
     optionally transcript_path).
  2. Load config, check guards: autoRecall, healthy, bankId, credentials.
  3. Extract prompt text (accepts both "prompt" and "user_prompt" keys).
  4. If prompt is empty or < 5 chars, exit silently.
  5. If recallContextTurns > 1 and transcript_path exists, read recent
     messages from the JSONL transcript and compose a multi-turn query.
  6. Truncate query to recallMaxQueryChars + apply a final defensive cap.
  7. Call client.recall(bank_id, query, ...).
  8. On 401/403 → systemMessage + additionalContext, mark_unhealthy,
     set error_notified flag.
     On 5xx/timeout → log to stderr, exit silently (retry next prompt).
  9. Check for server-side warnings and surface once via systemMessage.
 10. Apply recallTopK limit if set.
 11. Format memories via content.format_memories().
 12. If no results → exit silently (empty stdout, not empty JSON).
 13. Wrap in <hindsight_memories> tags and write the UserPromptSubmit output
     JSON to stdout.
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
from lib.content import (  # noqa: E402
    compose_recall_query,
    format_current_time,
    format_memories,
    truncate_recall_query,
)
from lib.state import (  # noqa: E402
    is_healthy,
    mark_unhealthy,
    read_session_state,
    set_flag,
)


def read_transcript_messages(transcript_path: str) -> list:
    """Read messages from a Claude Code JSONL transcript file.

    Handles both the nested format used by Claude Code
    (``{"type":"user","message":{"role":"user","content":"..."}}``),
    and a flat format (``{"role":"user","content":"..."}``) defensively.

    Args:
        transcript_path: Absolute path to the JSONL transcript file.

    Returns:
        List of ``{"role": str, "content": str|list}`` dicts in order,
        or an empty list on any read/parse error.
    """
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
                msg = entry.get("message")
                if isinstance(msg, dict) and "role" in msg:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role:
                        messages.append({"role": role, "content": content})
                    continue

                # Flat format: {"role": ..., "content": ...}
                role = entry.get("role", "")
                content = entry.get("content", "")
                if role:
                    messages.append({"role": role, "content": content})
    except (OSError, IOError):
        pass
    return messages


def main() -> None:
    """Run the UserPromptSubmit recall hook.

    Reads hook input from stdin, checks guards, composes a recall query,
    fetches relevant memories from Hindsight, and writes the formatted
    context block to stdout as a UserPromptSubmit output JSON.

    Exits 0 in all cases to avoid blocking the Claude Code session.
    Produces no stdout output when there are no results or on any error.
    """
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    config = load_config(hook_input)
    debug_log(config, "recall: loaded config for session", session_id)

    # Guard 1: autoRecall disabled
    if not config.get("autoRecall", True):
        debug_log(config, "recall: autoRecall disabled, skipping")
        return

    # Guard 2: session not healthy
    if not is_healthy(session_id):
        debug_log(config, "recall: session not healthy, skipping")
        return

    # Guard 3: need a bankId
    bank_id = config.get("bankId", "")
    if not bank_id:
        debug_log(config, "recall: no bankId resolved, skipping")
        return

    # Guard 4: need API URL + API key
    api_url = config.get("hindsightApiUrl", "")
    api_key = config.get("apiKey", "")
    if not api_url or not api_key:
        debug_log(config, "recall: missing hindsightApiUrl or apiKey, skipping")
        return

    # Extract prompt text
    prompt = hook_input.get("prompt") or hook_input.get("user_prompt") or ""
    prompt = prompt.strip()

    if len(prompt) < 5:
        debug_log(config, "recall: prompt too short, skipping")
        return

    # Compose multi-turn query if configured
    recall_context_turns = int(config.get("recallContextTurns", 1))
    recall_max_query_chars = int(config.get("recallMaxQueryChars", 800))

    messages = []
    if recall_context_turns > 1:
        transcript_path = hook_input.get("transcript_path", "")
        if transcript_path and os.path.isfile(transcript_path):
            messages = read_transcript_messages(transcript_path)
            debug_log(config, f"recall: read {len(messages)} messages from transcript")
        else:
            debug_log(config, "recall: transcript_path not available for multi-turn context")

    query = compose_recall_query(prompt, messages, recall_context_turns)
    query = truncate_recall_query(query, prompt, recall_max_query_chars)

    # Final defensive cap (matches upstream pattern)
    if recall_max_query_chars > 0 and len(query) > recall_max_query_chars:
        query = query[:recall_max_query_chars]

    debug_log(config, f"recall: query length={len(query)}, bank={bank_id}")

    # Build client and call recall
    client = HindclawClient(api_url=api_url, api_key=api_key)

    recall_budget = config.get("recallBudget", "mid")
    recall_max_tokens = int(config.get("recallMaxTokens", 1024))

    try:
        response = client.recall(
            bank_id,
            query,
            budget=recall_budget,
            max_tokens=recall_max_tokens,
        )
    except HindclawHttpError as exc:
        if exc.status_code in (401, 403):
            state = read_session_state(session_id)
            if not state.get("error_notified"):
                error_msg = f"HindClaw: memory access denied ({exc.status_code}). Check your API key and bank permissions."
                output = {
                    "systemMessage": error_msg,
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": f"<hindsight_error>{error_msg}</hindsight_error>",
                    },
                }
                json.dump(output, sys.stdout)
                set_flag(session_id, "error_notified", True)
            mark_unhealthy(session_id)
            return
        # 5xx or other — log and retry next prompt
        print(f"[HindClaw] recall: HTTP error {exc.status_code}: {exc.body}", file=sys.stderr)
        return
    except Exception as exc:
        print(f"[HindClaw] recall: unexpected error: {exc}", file=sys.stderr)
        return

    results = response.get("results", [])
    if not results:
        debug_log(config, "recall: no results returned")
        return

    # Check for server-side cap warnings
    system_message = None
    warnings = response.get("warnings")
    if warnings:
        state = read_session_state(session_id)
        if not state.get("config_warned"):
            system_message = f"HindClaw: {'; '.join(warnings)}. Update your config to avoid this warning."
            set_flag(session_id, "config_warned", True)

    # Apply recallTopK limit
    recall_top_k = config.get("recallTopK")
    if recall_top_k is not None:
        try:
            results = results[:int(recall_top_k)]
        except (TypeError, ValueError):
            pass

    if not results:
        debug_log(config, "recall: no results after topK filter")
        return

    # Format memories
    formatted = format_memories(results)
    if not formatted:
        debug_log(config, "recall: format_memories returned empty string")
        return

    preamble = (
        "Relevant memories from past conversations (prioritize recent when conflicting). "
        "Only use memories that are directly useful to continue this conversation; ignore the rest:"
    )
    current_time = format_current_time()
    context_message = (
        f"<hindsight_memories>\n"
        f"{preamble}\n"
        f"Current time - {current_time}\n\n"
        f"{formatted}\n"
        f"</hindsight_memories>"
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context_message,
        }
    }
    if system_message:
        output["systemMessage"] = system_message

    debug_log(config, f"recall: injecting {len(results)} memories from bank {bank_id!r}")
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[HindClaw] recall error: {exc}", file=sys.stderr)
        if os.environ.get("HINDCLAW_DEBUG"):
            sys.exit(2)
    sys.exit(0)

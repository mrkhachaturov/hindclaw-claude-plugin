"""Content processing utilities.

Faithful port of Openclaw plugin's content processing: memory tag stripping,
query composition/truncation, transcript formatting, and memory formatting.
"""

import re
from datetime import datetime, timezone

# --- Memory tag stripping ---


def strip_channel_envelope(content: str) -> str:
    """Strip ``<channel ...>...</channel>`` XML wrappers, returning the inner text.

    Args:
        content: Raw message string, possibly wrapped in a channel envelope.

    Returns:
        Inner content with leading/trailing whitespace stripped, or the original
        string unchanged when no channel envelope is found.
    """
    match = re.search(r"<channel\b[^>]*>([\s\S]*?)</channel>", content)
    if match:
        return match.group(1).strip()
    return content


def strip_memory_tags(content: str) -> str:
    """Remove ``<hindsight_memories>`` and ``<relevant_memories>`` blocks.

    Args:
        content: Raw message string that may contain memory injection blocks.

    Returns:
        String with all memory tag blocks removed.
    """
    content = re.sub(r"<hindsight_memories>[\s\S]*?</hindsight_memories>", "", content)
    content = re.sub(r"<relevant_memories>[\s\S]*?</relevant_memories>", "", content)
    return content


# --- Recall query ---


def compose_recall_query(
    latest_query: str,
    messages: list,
    recall_context_turns: int,
    recall_roles: list | None = None,
) -> str:
    """Build a multi-turn recall query from recent conversation context.

    Combines the latest user query with preceding turns so that the recall
    search has enough context to retrieve semantically relevant memories.

    Args:
        latest_query: The most recent user message text.
        messages: Full conversation message list (OpenClaw format).
        recall_context_turns: How many user-boundary turns to include as context.
            When <= 1 the function returns only ``latest_query``.
        recall_roles: Roles to include in context (default: ``["user", "assistant"]``).

    Returns:
        Either ``latest_query`` alone, or a string of the form::

            Prior context:
            <role>: <text>
            ...

            <latest_query>
    """
    latest = latest_query.strip()
    if recall_context_turns <= 1 or not isinstance(messages, list) or not messages:
        return latest
    allowed_roles = set(recall_roles or ["user", "assistant"])
    contextual_messages = slice_last_turns_by_user_boundary(messages, recall_context_turns)
    context_lines = []
    for msg in contextual_messages:
        role = msg.get("role")
        if role not in allowed_roles:
            continue
        content = _extract_text_content(msg.get("content", ""), role=role)
        content = strip_channel_envelope(content)
        content = strip_memory_tags(content).strip()
        if not content:
            continue
        if role == "user" and content == latest:
            continue
        context_lines.append(f"{role}: {content}")
    if not context_lines:
        return latest
    return "\n\n".join(["Prior context:", "\n".join(context_lines), latest])


def truncate_recall_query(query: str, latest_query: str, max_chars: int) -> str:
    """Truncate a recall query to ``max_chars``, preserving the latest message.

    Drops older context lines from the front until the query fits, falling
    back to ``latest_query`` alone if even one line pushes it over the limit.

    Args:
        query: Full recall query, possibly containing a "Prior context:" section.
        latest_query: The raw latest user message (always preserved).
        max_chars: Maximum character budget.  0 or negative means no limit.

    Returns:
        Truncated query string that fits within ``max_chars``.
    """
    if max_chars <= 0:
        return query
    latest = latest_query.strip()
    if len(query) <= max_chars:
        return query
    latest_only = latest[:max_chars] if len(latest) > max_chars else latest
    if "Prior context:" not in query:
        return latest_only
    context_marker = "Prior context:\n\n"
    marker_index = query.find(context_marker)
    if marker_index == -1:
        return latest_only
    suffix_marker = "\n\n" + latest
    suffix_index = query.rfind(suffix_marker)
    if suffix_index == -1:
        return latest_only
    suffix = query[suffix_index:]
    if len(suffix) >= max_chars:
        return latest_only
    context_body = query[marker_index + len(context_marker):suffix_index]
    context_lines = [line for line in context_body.split("\n") if line]
    kept = []
    for i in range(len(context_lines) - 1, -1, -1):
        kept.insert(0, context_lines[i])
        candidate = f"{context_marker}{chr(10).join(kept)}{suffix}"
        if len(candidate) > max_chars:
            kept.pop(0)
            break
    if kept:
        return f"{context_marker}{chr(10).join(kept)}{suffix}"
    return latest_only


# --- Turn slicing ---


def slice_last_turns_by_user_boundary(messages: list, turns: int) -> list:
    """Slice the last *N* turns from ``messages`` using user-message boundaries.

    A "turn" begins at each ``user`` role message.  The function walks backwards
    through the list and returns the suffix that starts at the N-th user message
    from the end.

    Args:
        messages: Full conversation message list.
        turns: Number of user-boundary turns to keep.  Must be > 0.

    Returns:
        A sub-list (or copy of all messages when there are fewer user turns
        than requested).  Returns an empty list for invalid inputs.
    """
    if not isinstance(messages, list) or not messages or turns <= 0:
        return []
    user_turns_seen = 0
    start_index = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_turns_seen += 1
            if user_turns_seen >= turns:
                start_index = i
                break
    if start_index == -1:
        return list(messages)
    return messages[start_index:]


# --- Memory formatting ---


def format_memories(results: list) -> str:
    """Format recall results as a human-readable bullet list.

    Each memory is rendered as ``- text [type] (date)``, with the type and
    date portions omitted when absent.

    Args:
        results: List of memory dicts with optional ``text``, ``type``, and
            ``mentioned_at`` keys.

    Returns:
        Memories joined by double newlines, or an empty string for empty input.
    """
    if not results:
        return ""
    lines = []
    for r in results:
        text = r.get("text", "")
        mem_type = r.get("type", "")
        mentioned_at = r.get("mentioned_at", "")
        type_str = f" [{mem_type}]" if mem_type else ""
        date_str = f" ({mentioned_at})" if mentioned_at else ""
        lines.append(f"- {text}{type_str}{date_str}")
    return "\n\n".join(lines)


def format_current_time() -> str:
    """Return the current UTC time formatted as ``YYYY-MM-DD HH:MM``.

    Returns:
        UTC timestamp string.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M")


# --- Retention transcript ---


def prepare_retention_transcript(
    messages: list,
    retain_roles: list | None = None,
    retain_full_window: bool = False,
) -> tuple:
    """Format a retention transcript from the conversation window.

    By default only the last user turn and everything after it are included.
    Pass ``retain_full_window=True`` to include the entire message list.

    Each message is wrapped as::

        [role: <role>]
        <content>
        [<role>:end]

    Args:
        messages: Full conversation message list.
        retain_roles: Roles to include (default: ``["user", "assistant"]``).
        retain_full_window: When ``True``, include all messages rather than
            only the last user turn.

    Returns:
        A ``(transcript, count)`` tuple where ``transcript`` is the formatted
        string and ``count`` is the number of message parts included.
        Returns ``(None, 0)`` when there is nothing meaningful to retain.
    """
    if not messages:
        return None, 0
    if retain_full_window:
        target_messages = messages
    else:
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx == -1:
            return None, 0
        target_messages = messages[last_user_idx:]
    allowed_roles = set(retain_roles or ["user", "assistant"])
    parts = []
    for msg in target_messages:
        role = msg.get("role", "unknown")
        if role not in allowed_roles:
            continue
        content = _extract_text_content(msg.get("content", ""), role=role)
        content = strip_channel_envelope(content)
        content = strip_memory_tags(content).strip()
        if not content:
            continue
        parts.append(f"[role: {role}]\n{content}\n[{role}:end]")
    if not parts:
        return None, 0
    transcript = "\n\n".join(parts)
    if len(transcript.strip()) < 10:
        return None, 0
    return transcript, len(parts)


# --- Helpers ---

_MESSAGE_TEXT_FIELDS = ("text", "body", "message", "content")

_OPERATIONAL_TOOL_PATTERN = re.compile(
    r"(?:recall|retain|reflect|search|extract|create_|delete_|update_|get_|list_)",
    re.IGNORECASE,
)


def _is_channel_message_tool(block: dict) -> bool:
    """Detect whether a tool_use block is a channel messaging call (not an operational tool).

    Returns True for MCP tools whose name does not match operational patterns and
    whose input dict contains a non-empty text-like field.

    Args:
        block: A ``tool_use`` content block dict.

    Returns:
        ``True`` if the block looks like a channel send, ``False`` otherwise.
    """
    name = block.get("name", "")
    if not name.startswith("mcp__"):
        return False
    tool_suffix = name.split("__")[-1]
    if _OPERATIONAL_TOOL_PATTERN.search(tool_suffix):
        return False
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        return False
    return any(isinstance(tool_input.get(f), str) and tool_input[f].strip() for f in _MESSAGE_TEXT_FIELDS)


def _extract_text_content(content, role: str = "") -> str:
    """Extract plain text from a message content value.

    Handles both raw strings and the structured content-blocks array format
    used by Claude Code hooks.  For assistant messages, channel-send tool_use
    blocks are also included.

    Args:
        content: Either a plain string or a list of content block dicts.
        role: The message role (``"assistant"`` enables tool_use extraction).

    Returns:
        Extracted text joined by newlines, or an empty string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "").strip()
                if text:
                    texts.append(text)
            elif block_type == "tool_use" and role == "assistant":
                if _is_channel_message_tool(block):
                    tool_input = block.get("input", {})
                    for field in _MESSAGE_TEXT_FIELDS:
                        val = tool_input.get(field)
                        if isinstance(val, str) and val.strip():
                            texts.append(val.strip())
                            break
        return "\n".join(texts)
    return ""

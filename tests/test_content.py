"""Tests for content processing utilities."""

import pytest

from scripts.lib.content import (
    strip_channel_envelope,
    strip_memory_tags,
    compose_recall_query,
    truncate_recall_query,
    slice_last_turns_by_user_boundary,
    format_memories,
    format_current_time,
    prepare_retention_transcript,
    _is_channel_message_tool,
    _extract_text_content,
)


# ---------------------------------------------------------------------------
# strip_channel_envelope
# ---------------------------------------------------------------------------

class TestStripChannelEnvelope:
    def test_strips_simple_channel_wrapper(self):
        content = "<channel name=\"test\">hello world</channel>"
        assert strip_channel_envelope(content) == "hello world"

    def test_strips_multiline_channel_content(self):
        content = "<channel id=\"abc\">\nline one\nline two\n</channel>"
        assert strip_channel_envelope(content) == "line one\nline two"

    def test_returns_original_when_no_wrapper(self):
        content = "plain text no channel"
        assert strip_channel_envelope(content) == "plain text no channel"

    def test_strips_channel_with_no_attributes(self):
        content = "<channel>inner content</channel>"
        assert strip_channel_envelope(content) == "inner content"

    def test_strips_channel_with_multiple_attributes(self):
        content = '<channel id="1" type="dm">message text</channel>'
        assert strip_channel_envelope(content) == "message text"

    def test_returns_empty_string_for_empty_input(self):
        assert strip_channel_envelope("") == ""

    def test_trims_whitespace_inside_channel(self):
        content = "<channel>   trimmed   </channel>"
        assert strip_channel_envelope(content) == "trimmed"


# ---------------------------------------------------------------------------
# strip_memory_tags
# ---------------------------------------------------------------------------

class TestStripMemoryTags:
    def test_strips_hindsight_memories_block(self):
        content = "before\n<hindsight_memories>memory data</hindsight_memories>\nafter"
        result = strip_memory_tags(content)
        assert "<hindsight_memories>" not in result
        assert "before" in result
        assert "after" in result

    def test_strips_relevant_memories_block(self):
        content = "start\n<relevant_memories>some memories</relevant_memories>\nend"
        result = strip_memory_tags(content)
        assert "<relevant_memories>" not in result
        assert "start" in result
        assert "end" in result

    def test_strips_both_memory_block_types(self):
        content = (
            "<hindsight_memories>h</hindsight_memories>"
            "middle"
            "<relevant_memories>r</relevant_memories>"
        )
        result = strip_memory_tags(content)
        assert "<hindsight_memories>" not in result
        assert "<relevant_memories>" not in result
        assert "middle" in result

    def test_no_change_when_no_memory_tags(self):
        content = "just regular content here"
        assert strip_memory_tags(content) == content

    def test_strips_multiline_memory_block(self):
        content = "before\n<hindsight_memories>\nline1\nline2\n</hindsight_memories>\nafter"
        result = strip_memory_tags(content)
        assert "line1" not in result
        assert "after" in result

    def test_empty_input_returns_empty(self):
        assert strip_memory_tags("") == ""


# ---------------------------------------------------------------------------
# compose_recall_query
# ---------------------------------------------------------------------------

class TestComposeRecallQuery:
    def test_returns_latest_only_when_turns_is_1(self):
        messages = [{"role": "user", "content": "previous"}]
        result = compose_recall_query("new question", messages, recall_context_turns=1)
        assert result == "new question"

    def test_returns_latest_only_when_messages_empty(self):
        result = compose_recall_query("query", [], recall_context_turns=3)
        assert result == "query"

    def test_returns_latest_only_when_messages_not_list(self):
        result = compose_recall_query("query", None, recall_context_turns=3)
        assert result == "query"

    def test_composes_with_prior_context(self):
        messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        result = compose_recall_query("second question", messages, recall_context_turns=3)
        assert "Prior context:" in result
        assert "first question" in result
        assert "second question" in result

    def test_skips_latest_query_duplicate_in_context(self):
        messages = [
            {"role": "user", "content": "the question"},
        ]
        result = compose_recall_query("the question", messages, recall_context_turns=3)
        # The latest query is duplicated — should just return latest_query
        assert result == "the question"

    def test_strips_memory_tags_from_context(self):
        messages = [
            {"role": "user", "content": "text <hindsight_memories>mem</hindsight_memories> rest"},
        ]
        result = compose_recall_query("new", messages, recall_context_turns=3)
        assert "<hindsight_memories>" not in result
        assert "mem" not in result

    def test_strips_channel_envelope_from_context(self):
        messages = [
            {"role": "user", "content": "<channel id=\"x\">inner text</channel>"},
        ]
        result = compose_recall_query("new query", messages, recall_context_turns=3)
        assert "<channel" not in result
        assert "inner text" in result

    def test_filters_by_recall_roles(self):
        messages = [
            {"role": "user", "content": "user msg"},
            {"role": "assistant", "content": "assistant msg"},
            {"role": "system", "content": "system msg"},
        ]
        result = compose_recall_query("latest", messages, recall_context_turns=5, recall_roles=["user"])
        assert "assistant msg" not in result
        assert "system msg" not in result

    def test_default_roles_include_user_and_assistant(self):
        messages = [
            {"role": "user", "content": "user msg"},
            {"role": "assistant", "content": "assistant msg"},
            {"role": "system", "content": "system msg"},
        ]
        result = compose_recall_query("latest", messages, recall_context_turns=5)
        assert "user msg" in result
        assert "assistant msg" in result
        assert "system msg" not in result

    def test_returns_latest_when_context_lines_empty_after_filtering(self):
        messages = [
            {"role": "system", "content": "system only"},
        ]
        result = compose_recall_query("query", messages, recall_context_turns=3, recall_roles=["user"])
        assert result == "query"

    def test_handles_content_blocks_array(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "block content"}]},
        ]
        result = compose_recall_query("new", messages, recall_context_turns=3)
        assert "block content" in result


# ---------------------------------------------------------------------------
# truncate_recall_query
# ---------------------------------------------------------------------------

class TestTruncateRecallQuery:
    def test_no_op_when_max_chars_zero(self):
        query = "a" * 200
        result = truncate_recall_query(query, "latest", max_chars=0)
        assert result == query

    def test_no_op_when_within_limit(self):
        query = "short query"
        result = truncate_recall_query(query, "short query", max_chars=100)
        assert result == query

    def test_truncates_simple_query_to_max_chars(self):
        latest = "x" * 20
        query = latest
        result = truncate_recall_query(query, latest, max_chars=10)
        assert len(result) <= 10

    def test_preserves_latest_when_no_prior_context(self):
        latest = "the actual question"
        long_query = "a" * 500
        result = truncate_recall_query(long_query, latest, max_chars=50)
        assert result == latest

    def test_truncates_prior_context_keeping_latest(self):
        latest = "final question"
        context_marker = "Prior context:\n\n"
        lines = ["line one", "line two", "line three", "line four", "line five"]
        context_body = "\n".join(lines)
        query = f"{context_marker}{context_body}\n\n{latest}"
        # Set max_chars to something that fits latest + few context lines
        max_chars = len(f"{context_marker}line five\n\n{latest}") + 5
        result = truncate_recall_query(query, latest, max_chars=max_chars)
        assert latest in result
        assert len(result) <= max_chars

    def test_falls_back_to_latest_only_when_even_one_line_exceeds_limit(self):
        latest = "q"
        context_marker = "Prior context:\n\n"
        long_line = "x" * 200
        query = f"{context_marker}{long_line}\n\n{latest}"
        # max_chars set so that even one context line exceeds the budget
        max_chars = len(f"{context_marker}\n\n{latest}") + 5
        result = truncate_recall_query(query, latest, max_chars=max_chars)
        assert result == latest

    def test_keeps_most_recent_context_lines(self):
        latest = "q"
        context_marker = "Prior context:\n\n"
        lines = ["first line", "second line", "third line"]
        context_body = "\n".join(lines)
        query = f"{context_marker}{context_body}\n\n{latest}"
        # Enough for third line + latest but not all three lines
        max_chars = len(f"{context_marker}third line\n\n{latest}") + 5
        result = truncate_recall_query(query, latest, max_chars=max_chars)
        assert "third line" in result
        assert "first line" not in result


# ---------------------------------------------------------------------------
# slice_last_turns_by_user_boundary
# ---------------------------------------------------------------------------

class TestSliceLastTurnsByUserBoundary:
    def test_returns_empty_for_empty_messages(self):
        assert slice_last_turns_by_user_boundary([], turns=3) == []

    def test_returns_empty_for_non_list(self):
        assert slice_last_turns_by_user_boundary(None, turns=3) == []

    def test_returns_empty_for_zero_turns(self):
        msgs = [{"role": "user", "content": "hi"}]
        assert slice_last_turns_by_user_boundary(msgs, turns=0) == []

    def test_returns_all_when_fewer_user_turns_than_requested(self):
        msgs = [
            {"role": "user", "content": "only user"},
            {"role": "assistant", "content": "only assistant"},
        ]
        result = slice_last_turns_by_user_boundary(msgs, turns=5)
        assert result == msgs

    def test_slices_last_n_user_boundaries(self):
        msgs = [
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "answer 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "assistant", "content": "answer 2"},
            {"role": "user", "content": "turn 3"},
        ]
        result = slice_last_turns_by_user_boundary(msgs, turns=2)
        # Should start from the second-to-last user message (index 2)
        assert result[0]["content"] == "turn 2"
        assert len(result) == 3

    def test_slices_exactly_one_turn(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        result = slice_last_turns_by_user_boundary(msgs, turns=1)
        assert result[0]["content"] == "second"
        assert len(result) == 1

    def test_includes_messages_after_user_turn_start(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        result = slice_last_turns_by_user_boundary(msgs, turns=1)
        assert result == [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]


# ---------------------------------------------------------------------------
# format_memories
# ---------------------------------------------------------------------------

class TestFormatMemories:
    def test_returns_empty_string_for_empty_list(self):
        assert format_memories([]) == ""

    def test_formats_single_memory_with_type_and_date(self):
        results = [{"text": "remember this", "type": "fact", "mentioned_at": "2026-01-01"}]
        result = format_memories(results)
        assert "- remember this [fact] (2026-01-01)" == result

    def test_formats_memory_without_type(self):
        results = [{"text": "no type here", "mentioned_at": "2026-01-01"}]
        result = format_memories(results)
        assert "- no type here (2026-01-01)" == result

    def test_formats_memory_without_date(self):
        results = [{"text": "no date", "type": "note"}]
        result = format_memories(results)
        assert "- no date [note]" == result

    def test_formats_memory_without_type_or_date(self):
        results = [{"text": "bare text"}]
        result = format_memories(results)
        assert "- bare text" == result

    def test_joins_multiple_memories_with_double_newline(self):
        results = [
            {"text": "first", "type": "a", "mentioned_at": "2026-01-01"},
            {"text": "second", "type": "b", "mentioned_at": "2026-01-02"},
        ]
        result = format_memories(results)
        parts = result.split("\n\n")
        assert len(parts) == 2
        assert parts[0].startswith("- first")
        assert parts[1].startswith("- second")


# ---------------------------------------------------------------------------
# format_current_time
# ---------------------------------------------------------------------------

class TestFormatCurrentTime:
    def test_returns_string(self):
        result = format_current_time()
        assert isinstance(result, str)

    def test_matches_expected_format(self):
        import re
        result = format_current_time()
        # Expected: YYYY-MM-DD HH:MM
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", result)

    def test_uses_utc_time(self):
        from unittest.mock import patch
        from datetime import datetime, timezone
        fixed_utc = datetime(2026, 3, 23, 14, 30, tzinfo=timezone.utc)
        with patch("scripts.lib.content.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_utc
            mock_dt.now.side_effect = lambda tz=None: fixed_utc
            result = format_current_time()
        assert result == "2026-03-23 14:30"


# ---------------------------------------------------------------------------
# prepare_retention_transcript
# ---------------------------------------------------------------------------

class TestPrepareRetentionTranscript:
    def test_returns_none_for_empty_messages(self):
        transcript, count = prepare_retention_transcript([])
        assert transcript is None
        assert count == 0

    def test_returns_none_when_no_user_message(self):
        msgs = [{"role": "assistant", "content": "assistant only"}]
        transcript, count = prepare_retention_transcript(msgs)
        assert transcript is None
        assert count == 0

    def test_formats_last_user_turn_only_by_default(self):
        msgs = [
            {"role": "user", "content": "first user"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second user"},
            {"role": "assistant", "content": "second answer"},
        ]
        transcript, count = prepare_retention_transcript(msgs)
        assert "second user" in transcript
        assert "second answer" in transcript
        # Full window not requested — first turn should not appear
        assert "first user" not in transcript

    def test_full_window_includes_all_messages(self):
        msgs = [
            {"role": "user", "content": "first user"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second user"},
        ]
        transcript, count = prepare_retention_transcript(msgs, retain_full_window=True)
        assert "first user" in transcript
        assert "first answer" in transcript
        assert "second user" in transcript
        assert count == 3

    def test_wraps_each_message_in_role_tags(self):
        msgs = [{"role": "user", "content": "test content"}]
        transcript, count = prepare_retention_transcript(msgs)
        assert "[role: user]" in transcript
        assert "test content" in transcript
        assert "[user:end]" in transcript

    def test_filters_by_retain_roles(self):
        msgs = [
            {"role": "user", "content": "user msg"},
            {"role": "assistant", "content": "assistant msg"},
        ]
        transcript, count = prepare_retention_transcript(
            msgs, retain_roles=["user"], retain_full_window=True
        )
        assert "user msg" in transcript
        assert "assistant msg" not in transcript
        assert count == 1

    def test_skips_messages_with_empty_content(self):
        msgs = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "real content"},
        ]
        transcript, count = prepare_retention_transcript(msgs, retain_full_window=True)
        assert "real content" in transcript
        assert count == 1

    def test_strips_channel_envelope_from_content(self):
        msgs = [{"role": "user", "content": "<channel>inner</channel>"}]
        transcript, count = prepare_retention_transcript(msgs)
        assert "<channel>" not in transcript
        assert "inner" in transcript

    def test_strips_memory_tags_from_content(self):
        msgs = [{"role": "user", "content": "text <hindsight_memories>mem</hindsight_memories> end"}]
        transcript, count = prepare_retention_transcript(msgs)
        assert "<hindsight_memories>" not in transcript
        assert "mem" not in transcript

    def test_returns_none_when_transcript_too_short(self):
        # The 10-char threshold is checked against the assembled transcript
        # (including role wrappers), not the raw content.  A single whitespace-
        # only message collapses to an empty part — no parts → None.
        msgs = [{"role": "user", "content": "   "}]
        transcript, count = prepare_retention_transcript(msgs)
        assert transcript is None
        assert count == 0

    def test_count_matches_number_of_parts(self):
        msgs = [
            {"role": "user", "content": "first user question here"},
            {"role": "assistant", "content": "first assistant response here"},
        ]
        transcript, count = prepare_retention_transcript(msgs, retain_full_window=True)
        assert count == 2

    def test_handles_content_blocks_list(self):
        msgs = [{
            "role": "user",
            "content": [{"type": "text", "text": "block text content here"}]
        }]
        transcript, count = prepare_retention_transcript(msgs)
        assert "block text content here" in transcript


# ---------------------------------------------------------------------------
# _is_channel_message_tool
# ---------------------------------------------------------------------------

class TestIsChannelMessageTool:
    def test_returns_false_for_non_mcp_tool(self):
        block = {"name": "send_message", "input": {"text": "hello"}}
        assert _is_channel_message_tool(block) is False

    def test_returns_false_for_operational_recall_tool(self):
        block = {"name": "mcp__hindclaw__recall", "input": {"query": "q"}}
        assert _is_channel_message_tool(block) is False

    def test_returns_false_for_operational_retain_tool(self):
        block = {"name": "mcp__hindclaw__retain", "input": {"text": "t"}}
        assert _is_channel_message_tool(block) is False

    def test_returns_false_for_operational_search_tool(self):
        block = {"name": "mcp__server__search_results", "input": {"text": "t"}}
        assert _is_channel_message_tool(block) is False

    def test_returns_true_for_mcp_send_message_tool(self):
        block = {
            "name": "mcp__telegram__send",
            "input": {"text": "hello world"},
        }
        assert _is_channel_message_tool(block) is True

    def test_returns_false_when_input_not_dict(self):
        block = {"name": "mcp__telegram__send", "input": "not a dict"}
        assert _is_channel_message_tool(block) is False

    def test_returns_false_when_no_text_fields(self):
        block = {"name": "mcp__telegram__send", "input": {"other_field": 123}}
        assert _is_channel_message_tool(block) is False

    def test_returns_false_when_text_field_is_empty(self):
        block = {"name": "mcp__telegram__send", "input": {"text": "   "}}
        assert _is_channel_message_tool(block) is False

    def test_recognizes_body_field(self):
        block = {"name": "mcp__channel__post", "input": {"body": "message body"}}
        assert _is_channel_message_tool(block) is True

    def test_recognizes_message_field(self):
        block = {"name": "mcp__channel__post", "input": {"message": "hello"}}
        assert _is_channel_message_tool(block) is True

    def test_recognizes_content_field(self):
        block = {"name": "mcp__channel__post", "input": {"content": "some content"}}
        assert _is_channel_message_tool(block) is True


# ---------------------------------------------------------------------------
# _extract_text_content
# ---------------------------------------------------------------------------

class TestExtractTextContent:
    def test_returns_string_content_unchanged(self):
        assert _extract_text_content("hello world") == "hello world"

    def test_returns_empty_string_for_unknown_type(self):
        assert _extract_text_content(42) == ""

    def test_extracts_text_blocks_from_list(self):
        content = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
        result = _extract_text_content(content)
        assert "first" in result
        assert "second" in result

    def test_skips_non_dict_blocks(self):
        content = ["string_block", {"type": "text", "text": "valid"}]
        result = _extract_text_content(content)
        assert result == "valid"

    def test_skips_empty_text_blocks(self):
        content = [{"type": "text", "text": "   "}, {"type": "text", "text": "good"}]
        result = _extract_text_content(content)
        assert result == "good"

    def test_extracts_tool_use_message_for_assistant_role(self):
        content = [{
            "type": "tool_use",
            "name": "mcp__channel__send",
            "input": {"text": "channel message"},
        }]
        result = _extract_text_content(content, role="assistant")
        assert "channel message" in result

    def test_ignores_tool_use_for_user_role(self):
        content = [{
            "type": "tool_use",
            "name": "mcp__channel__send",
            "input": {"text": "channel message"},
        }]
        result = _extract_text_content(content, role="user")
        assert result == ""

    def test_ignores_operational_tool_use(self):
        content = [{
            "type": "tool_use",
            "name": "mcp__hindclaw__recall",
            "input": {"text": "memory query"},
        }]
        result = _extract_text_content(content, role="assistant")
        assert result == ""

    def test_joins_multiple_text_blocks_with_newline(self):
        content = [
            {"type": "text", "text": "line one"},
            {"type": "text", "text": "line two"},
        ]
        result = _extract_text_content(content)
        assert result == "line one\nline two"

    def test_returns_empty_string_for_empty_list(self):
        assert _extract_text_content([]) == ""

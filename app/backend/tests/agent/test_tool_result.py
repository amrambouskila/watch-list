"""The wire shape every tool handler returns to the SDK."""

from __future__ import annotations

from tv_watchlist.agent.tool_result import text_result


def test_text_result_is_a_single_text_block_that_is_not_an_error() -> None:
    assert text_result("hello") == {"content": [{"type": "text", "text": "hello"}], "is_error": False}


def test_text_result_marks_failure_with_the_snake_case_key_the_sdk_reads() -> None:
    assert text_result("boom", is_error=True)["is_error"] is True

"""Markup reduced to the readable text the model is meant to see."""

from __future__ import annotations

from tv_watchlist.agent.html_text import html_to_text


def test_script_and_style_bodies_are_dropped_rather_than_read_as_prose() -> None:
    markup = "<html><head><style>.a{color:red}</style></head><body><script>var x=1</script><p>Dunkirk</p></body></html>"
    assert html_to_text(markup) == "Dunkirk"


def test_tags_become_separators_so_adjacent_elements_do_not_run_together() -> None:
    assert html_to_text("<li>Dunkirk</li><li>Fury</li>") == "Dunkirk Fury"


def test_entities_are_decoded() -> None:
    assert html_to_text("<p>Schindler&#39;s List &amp; Fury</p>") == "Schindler's List & Fury"


def test_runs_of_whitespace_collapse_to_one_space() -> None:
    assert html_to_text("<p>Das   Boot\n\n\tredux</p>") == "Das Boot redux"

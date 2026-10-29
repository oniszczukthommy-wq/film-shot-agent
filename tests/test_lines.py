"""Line search: matching, context window, highlight spans."""

from film_shot_agent.services.lines import highlight_spans, pipeline, search_lines


def test_searches_original_text(session):
    hits = search_lines(session, "robot")
    assert len(hits) >= 2
    assert all("robot" in hit.text.lower() for hit in hits)


def test_searches_chinese_translation(session):
    hits = search_lines(session, "机器人")
    assert hits, "中文翻译也要能搜到"
    assert hits[0].text_zh == "机器人"


def test_hit_carries_previous_and_next_line(session):
    hits = search_lines(session, "freaked out")
    assert hits
    hit = hits[0]
    assert hit.prev is not None
    assert hit.next is not None


def test_first_line_has_no_previous(session):
    hits = search_lines(session, "robotics")
    assert hits
    assert hits[0].prev is None


def test_highlight_spans_cover_the_phrase():
    spans = highlight_spans("my robot hand is cold", "robot hand")
    assert spans == ((3, 13),)


def test_highlight_falls_back_to_tokens():
    spans = highlight_spans("robot hand", "robot cold")
    assert spans == ((0, 5),)


def test_highlight_is_case_insensitive():
    assert highlight_spans("Robot", "robot") == ((0, 5),)


def test_empty_query_returns_nothing(session):
    assert search_lines(session, "   ") == []


def test_pipeline_links_line_to_onscreen_shot(session):
    hits = search_lines(session, "robot")
    payload = pipeline(session, hits[0])
    assert payload["shot_id"].startswith("alpha-")
    assert payload["shot_thumb"].endswith(".jpg")

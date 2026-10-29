"""Rule-first agent: intent, filters and trace."""

from film_shot_agent.services.agent import answer, extract_keyword


def test_look_sentence_becomes_shot_search(session):
    reply = answer(session, "找冷色调、暗一点的镜头")
    assert reply.intent == "shot"
    assert reply.filters.color_temp == "cool"
    assert reply.filters.brightness == "dark"
    assert [call.tool for call in reply.trace] == ["search_shots"]
    assert reply.trace[0].count == 5


def test_line_sentence_becomes_line_search(session):
    reply = answer(session, "说 robot 的台词")
    assert reply.intent == "line"
    assert [call.tool for call in reply.trace] == ["search_lines"]
    assert reply.lines
    assert reply.lines[0]["shot_id"]


def test_quoted_phrase_is_used_verbatim(session):
    reply = answer(session, "「robot hand」这句")
    assert reply.trace[0].args["q"] == "robot hand"


def test_title_name_is_extracted_from_sentence():
    titles = []
    assert extract_keyword("钢铁之泪里说 robot 的台词", titles) == "robot"


def test_every_reply_has_a_replayable_path(session):
    reply = answer(session, "暖调长镜头")
    assert reply.filters.path().startswith("/color_temp/warm")
    assert reply.payload()["path"] == reply.filters.path()


def test_reply_suggests_next_moves(session):
    reply = answer(session, "暖调")
    assert reply.followups
    assert isinstance(reply.followups[0], str)

"""Deck export: grid composition and the print view. ffmpeg is stubbed."""

import pytest

from film_shot_agent.domain.models import Cue, Deck, DeckItem
from film_shot_agent.services import deck_export, decks


def _deck(session, *refs) -> Deck:
    deck = decks.create_deck(session, "导出板")
    for kind, ref in refs:
        decks.add_item(session, deck.id, kind, ref)
    session.flush()
    return deck


def test_collage_requires_at_least_one_shot(session):
    deck = decks.create_deck(session, "空板")
    session.flush()
    with pytest.raises(decks.DeckError):
        deck_export.collage(session, deck.id)


def test_collage_reads_lines_as_their_onscreen_shot(session, monkeypatch, tmp_path):
    deck = _deck(session, ("cue", "alpha-cue-002"))
    seen: list[list] = []

    def fake_fit(src, dst, width):
        seen.append(src)
        dst.write_bytes(b"x")

    monkeypatch.setattr(deck_export, "_fit", fake_fit)
    monkeypatch.setattr(
        deck_export.ffmpeg,
        "grid_images",
        lambda sources, out, **kw: (seen.append(sources), out.write_bytes(b"jpg"), (0, ""))[2],
    )
    path = deck_export.collage(session, deck.id)
    assert path.exists()
    assert len(seen[1]) == 1


def test_print_html_contains_titles_timecodes_and_credit(session):
    deck = _deck(session, ("shot", "alpha-000"), ("cue", "alpha-cue-003"))
    html = deck_export.print_html(session, deck.id)
    assert "阿尔法" in html
    assert "00:00" in html or "0:00" in html
    assert "CC BY 3.0 demo" in html
    assert "@page" in html and "window.print()" in html


def test_print_html_escapes_content(session):
    deck = decks.create_deck(session, "<script>x</script>")
    session.flush()
    html = deck_export.print_html(session, deck.id)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_print_html_rejects_unknown_deck(session):
    with pytest.raises(decks.DeckError):
        deck_export.print_html(session, "nope")


def test_cue_items_are_resolved_through_their_title(session):
    cue = session.get(Cue, "alpha-cue-001")
    shot = deck_export._shot_for_cue(session, cue)
    assert shot is not None
    assert shot.title_id == cue.title_id


def test_deck_items_survive_ordering(session):
    deck = _deck(session, ("shot", "alpha-001"), ("shot", "alpha-002"))
    items = list(session.query(DeckItem).filter_by(deck_id=deck.id).order_by(DeckItem.position))
    assert [item.ref_id for item in items] == ["alpha-001", "alpha-002"]

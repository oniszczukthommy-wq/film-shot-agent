"""Filters, path encoding and faceted counts."""

from film_shot_agent.services.search import (
    ShotFilters,
    facet_counts,
    parse_filters,
    query_shots,
)


def test_path_roundtrip(session):
    filters = ShotFilters(color_temp="cool", brightness="dark", length="long")
    parsed = parse_filters([s for s in filters.path().strip("/").split("/")])
    assert parsed.color_temp == "cool"
    assert parsed.brightness == "dark"
    assert parsed.length == "long"


def test_unknown_keys_are_ignored():
    parsed = parse_filters(["nonsense", "x", "color_temp", "warm"])
    assert parsed.color_temp == "warm"
    assert parsed.path() == "/color_temp/warm"


def test_shade_path_carries_tolerance_and_proportion():
    filters = ShotFilters(shade="3a6ea5", distance=12, proportion=25)
    parsed = parse_filters(["shade", "3a6ea5~12~25"])
    assert (parsed.shade, parsed.distance, parsed.proportion) == ("3a6ea5", 12, 25)
    assert filters.path() == "/shade/3a6ea5~12~25"


def test_query_applies_single_dimension(session):
    rows, total = query_shots(session, ShotFilters(color_temp="cool"))
    assert total == 10
    assert all(shot.color_temp == "cool" for shot in rows)


def test_query_combines_dimensions(session):
    rows, total = query_shots(session, ShotFilters(color_temp="cool", brightness="bright"))
    assert total == 5  # alpha 中每隔三个一组的 cool 镜头，只有一半落在 bright 组
    rows, total = query_shots(session, ShotFilters(title="beta"))
    assert total == 1


def test_facet_counts_ignore_their_own_dimension(session):
    facets = facet_counts(session, ShotFilters(color_temp="cool"))
    counts = {item["value"]: item["count"] for item in facets["color_temp"]}
    assert counts["cool"] == 10
    assert counts["warm"] == 11  # 仍能看到别的色调还有多少
    assert sum(item["count"] for item in facets["color_temp"]) == 31


def test_facet_marks_selection(session):
    facets = facet_counts(session, ShotFilters(color_temp="cool"))
    selected = [item for item in facets["color_temp"] if item["selected"]]
    assert [item["value"] for item in selected] == ["cool"]


def test_shade_filter_matches_palette(session):
    rows, total = query_shots(session, ShotFilters(shade="1b2a4a", distance=8, proportion=40))
    assert total >= 10
    assert all(shot.color_temp == "cool" for shot in rows)


def test_shade_filter_rejects_far_colours(session):
    _, total = query_shots(session, ShotFilters(shade="ff0000", distance=4, proportion=1))
    assert total == 0


def test_title_filter_uses_slug(session):
    rows, total = query_shots(session, ShotFilters(title="alpha"))
    assert total == 30


def test_facets_respect_the_color_filter(session):
    filters = ShotFilters(shade="1b2a4a", distance=8, proportion=40)
    facets = facet_counts(session, filters)
    total = sum(item["count"] for item in facets["color_temp"])
    rows, expected_total = query_shots(session, filters)
    assert total == expected_total

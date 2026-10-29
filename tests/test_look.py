"""Pixel-derived look attributes."""

import pytest

from film_shot_agent.services.look import analyze, color_distance, hex_to_rgb


def _frame(color: tuple[int, int, int], count: int = 64 * 36) -> bytes:
    return bytes(color) * count


def test_palette_of_solid_frame_is_that_colour():
    look = analyze(_frame((128, 128, 130)), 64, 36)
    assert look.palette[0].hex == "#808082"
    assert look.palette[0].weight == pytest.approx(1.0)
    assert look.color_temp == "mono"  # 近中性灰判为黑白/低彩


def test_brightness_and_contrast_split_dark_from_bright():
    dark = analyze(_frame((10, 10, 12)), 64, 36)
    bright = analyze(_frame((220, 220, 215)), 64, 36)
    assert dark.brightness < bright.brightness
    assert dark.brightness_bucket == "dark"
    assert bright.brightness_bucket == "bright"


def test_warm_and_cool_are_separated():
    warm = analyze(_frame((200, 110, 30)), 64, 36)
    cool = analyze(_frame((20, 90, 200)), 64, 36)
    assert warm.color_temp == "warm"
    assert cool.color_temp == "cool"


def test_two_tone_frame_produces_more_than_one_swatch():
    frame = bytes((200, 60, 40)) * (64 * 36 // 2) + bytes((20, 60, 200)) * (64 * 36 // 2)
    look = analyze(frame, 64, 36)
    assert len(look.palette) >= 2
    assert sum(swatch.weight for swatch in look.palette) == pytest.approx(1.0, abs=0.02)


def test_colour_distance_is_small_for_near_colours():
    assert color_distance(hex_to_rgb("3a6ea5"), hex_to_rgb("3d70a8")) < 5
    assert color_distance(hex_to_rgb("3a6ea5"), hex_to_rgb("f0a45c")) > 30


def test_empty_frame_is_rejected():
    with pytest.raises(ValueError):
        analyze(b"", 64, 36)

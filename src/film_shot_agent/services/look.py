"""Machine-computed look attributes: palette, brightness, contrast, saturation, tone.

Everything here is derived from decoded pixels, so no manual tagging is required.
"""

import colorsys
import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Swatch:
    hex: str
    weight: float


@dataclass(frozen=True)
class Look:
    palette: tuple[Swatch, ...]
    brightness: float
    contrast: float
    saturation: float
    color_temp: str
    brightness_bucket: str
    contrast_bucket: str
    saturation_bucket: str
    dominant_hex: str


def normalize_hex(value: str | None) -> str | None:
    """Accept #abc / abcdef only; return a 6-digit lowercase hex or None."""
    if not value:
        return None
    candidate = value.strip().lstrip("#").lower()
    if len(candidate) == 3 and all(ch in "0123456789abcdef" for ch in candidate):
        candidate = "".join(ch * 2 for ch in candidate)
    if len(candidate) == 6 and all(ch in "0123456789abcdef" for ch in candidate):
        return candidate
    return None


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02x}" for channel in rgb)


def luma(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Perceptual-ish distance in 0..100 (weighted RGB, cheap and stable)."""
    rmean = (a[0] + b[0]) / 2
    dr = a[0] - b[0]
    dg = a[1] - b[1]
    db = a[2] - b[2]
    value = math.sqrt((2 + rmean / 256) * dr**2 + 4 * dg**2 + (2 + (255 - rmean) / 256) * db**2)
    return value / 7.65  # ≈0..100


def analyze(rgb: bytes, width: int, height: int, k: int = 5, seed: int = 7) -> Look:
    pixels = [
        (rgb[i], rgb[i + 1], rgb[i + 2])
        for i in range(0, min(len(rgb), width * height * 3) - 2, 3)
    ]
    if not pixels:
        raise ValueError("没有可分析的像素。")

    lumas = [luma(*p) for p in pixels]
    mean = sum(lumas) / len(lumas)
    variance = sum((value - mean) ** 2 for value in lumas) / len(lumas)
    saturations = [colorsys.rgb_to_hsv(*(c / 255 for c in p))[1] for p in pixels]
    mean_sat = sum(saturations) / len(saturations)

    swatches = _cluster(pixels, k=k, seed=seed)
    dominant = swatches[0].hex if swatches else rgb_to_hex(pixels[0])
    tone = _tone(pixels, mean_sat)

    return Look(
        palette=tuple(swatches),
        brightness=round(mean / 255, 4),
        contrast=round(min(1.0, math.sqrt(variance) / 80), 4),
        saturation=round(mean_sat, 4),
        color_temp=tone,
        brightness_bucket=_bucket(mean / 255, 0.28, 0.60, "dark", "mid", "bright"),
        contrast_bucket=_bucket(
            min(1.0, math.sqrt(variance) / 80), 0.18, 0.38, "low", "mid", "high"
        ),
        saturation_bucket=_bucket(mean_sat, 0.22, 0.45, "muted", "mid", "vivid"),
        dominant_hex=dominant.lower(),
    )


def _bucket(value: float, low: float, high: float, low_name: str, mid: str, high_name: str) -> str:
    if value < low:
        return low_name
    if value < high:
        return mid
    return high_name


def _tone(pixels: list[tuple[int, int, int]], mean_sat: float) -> str:
    if mean_sat < 0.12:
        return "mono"
    warm = cool = 0.0
    for r, g, b in pixels:
        hue, sat, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if sat < 0.1:
            continue
        degrees = hue * 360
        if degrees <= 60 or degrees >= 300:
            warm += sat
        elif 150 <= degrees <= 260:
            cool += sat
    total = warm + cool
    if total == 0:
        return "neutral"
    if warm / total > 0.58:
        return "warm"
    if cool / total > 0.58:
        return "cool"
    return "mixed"


def _cluster(
    pixels: list[tuple[int, int, int]], k: int, seed: int
) -> list[Swatch]:
    sample = pixels if len(pixels) <= 2000 else random.Random(seed).sample(pixels, 2000)
    centers = _seed_centers(sample, k, seed)
    for _ in range(8):
        buckets: list[list[tuple[int, int, int]]] = [[] for _ in centers]
        for pixel in sample:
            index = min(
                range(len(centers)),
                key=lambda i: (pixel[0] - centers[i][0]) ** 2
                + (pixel[1] - centers[i][1]) ** 2
                + (pixel[2] - centers[i][2]) ** 2,
            )
            buckets[index].append(pixel)
        moved = []
        for center, bucket in zip(centers, buckets, strict=True):
            if not bucket:
                moved.append(center)
                continue
            moved.append(
                tuple(sum(p[i] for p in bucket) / len(bucket) for i in range(3))  # type: ignore[misc]
            )
        if moved == centers:
            break
        centers = moved  # type: ignore[assignment]

    buckets = [[] for _ in centers]
    for pixel in sample:
        index = min(
            range(len(centers)),
            key=lambda i: (pixel[0] - centers[i][0]) ** 2
            + (pixel[1] - centers[i][1]) ** 2
            + (pixel[2] - centers[i][2]) ** 2,
        )
        buckets[index].append(pixel)

    total = sum(len(b) for b in buckets) or 1
    swatches = [
        Swatch(hex=rgb_to_hex(center), weight=round(len(bucket) / total, 4))
        for center, bucket in zip(centers, buckets, strict=True)
        if bucket
    ]
    swatches.sort(key=lambda s: s.weight, reverse=True)
    return swatches


def _seed_centers(pixels: list[tuple[int, int, int]], k: int, seed: int):
    rng = random.Random(seed)
    centers = [pixels[rng.randrange(len(pixels))]]
    while len(centers) < k:
        distances = [
            min(sum((p[i] - c[i]) ** 2 for i in range(3)) for c in centers) for p in pixels
        ]
        total = sum(distances)
        if total == 0:
            centers.append(pixels[rng.randrange(len(pixels))])
            continue
        target = rng.random() * total
        running = 0.0
        for pixel, distance in zip(pixels, distances, strict=True):
            running += distance
            if running >= target:
                centers.append(pixel)
                break
        else:
            centers.append(pixels[-1])
    return centers

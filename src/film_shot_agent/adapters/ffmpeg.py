"""Thin ffmpeg adapter. All media work happens on files we already own."""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")
_STREAM = re.compile(r"Stream #\d+:\d+.*?: Video: .*?, (\d+)x(\d+)")
_PTS = re.compile(r"pts_time:([0-9.]+)")
_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration_ms: int


def ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed binary, no shell
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def _run_binary(args: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed binary, no shell
        args, capture_output=True, timeout=timeout, check=False
    )


def probe(path: Path) -> MediaInfo:
    result = _run([ffmpeg_exe(), "-hide_banner", "-i", str(path)])
    text = result.stderr
    duration = _DURATION.search(text)
    stream = _STREAM.search(text)
    if not duration or not stream:
        raise ValueError(f"无法读取媒体信息：{path.name}")
    hours, minutes, seconds = duration.groups()
    return MediaInfo(
        width=int(stream.group(1)),
        height=int(stream.group(2)),
        duration_ms=int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000),
    )


def detect_aspect(path: Path, sample_frames: int = 90) -> float:
    """Use cropdetect to find the active picture area inside letterbox/pillarbox."""
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-ss", "10", "-i", str(path),
            "-vf", "cropdetect=24:2:0", "-frames:v", str(sample_frames),
            "-f", "null", "-",
        ]
    )
    matches = _CROP.findall(result.stderr)
    if not matches:
        return 0.0
    width, height = (int(value) for value in matches[-1][:2])
    return round(width / height, 3) if height else 0.0


def scene_cuts(path: Path, threshold: float) -> list[float]:
    """Return timestamps (seconds) where the picture changes, via one decode pass."""
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-i", str(path),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-vsync", "vfr", "-f", "null", "-",
        ],
        timeout=1800,
    )
    times = [float(value) for value in _PTS.findall(result.stderr)]
    return sorted(set(times))


def extract_frame(path: Path, seconds: float, out: Path, width: int) -> None:
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(0.0, seconds):.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
        ]
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"抽帧失败：{out.name} {result.stderr[:200]}")


def raw_rgb(path: Path, seconds: float, width: int = 64, height: int = 36) -> bytes:
    result = _run_binary(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, seconds):.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-",
        ]
    )
    if result.returncode != 0 or len(result.stdout) < width * height * 3:
        raise RuntimeError("读取原始帧失败。")
    return result.stdout


def make_clip(path: Path, start_ms: int, end_ms: int, out: Path) -> None:
    duration = max(300, end_ms - start_ms)
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start_ms / 1000:.3f}", "-i", str(path),
            "-t", f"{duration / 1000:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
            str(out),
        ],
        timeout=600,
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"切片失败：{result.stderr[:200]}")


def make_gif(path: Path, start_ms: int, end_ms: int, out: Path, width: int) -> None:
    duration = max(300, end_ms - start_ms)
    filters = (
        f"fps=12,scale={width}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"
    )
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start_ms / 1000:.3f}", "-i", str(path),
            "-t", f"{duration / 1000:.3f}", "-vf", filters, "-loop", "0", str(out),
        ],
        timeout=600,
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"GIF 生成失败：{result.stderr[:200]}")


def retime(source: Path, out: Path, target_height: int = 720) -> None:
    """Re-encode an owned source into a compact demo-quality file."""
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf", f"scale=-2:{target_height}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "27",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            str(out),
        ],
        timeout=3600,
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"转码失败：{result.stderr[:300]}")


def format_timestamp(ms: int) -> str:
    total_seconds, millis = divmod(max(0, ms), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis // 10:02d}"


def as_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def grid_images(
    sources: list[Path],
    out: Path,
    *,
    columns: int,
    cell_width: int,
    cell_height: int,
    padding: int,
) -> tuple[int, str]:
    """Compose images into a grid via explicit xstack, so cell order is deterministic."""
    if not sources:
        return 1, "没有可拼图的输入"
    if len(sources) == 1:
        return _scale_returning(sources[0], out, cell_width, cell_height)

    args = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for source in sources:
        args += ["-i", str(source)]

    chains = []
    for index in range(len(sources)):
        chains.append(
            f"[{index}:v]scale={cell_width}:{cell_height}:force_original_aspect_ratio=decrease,"
            f"pad={cell_width}:{cell_height}:(ow-iw)/2:(oh-ih)/2:color=0x0b0c0e[v{index}]"
        )
    layout = "|".join(
        f"{(index % columns) * (cell_width + padding)}_"
        f"{(index // columns) * (cell_height + padding)}"
        for index in range(len(sources))
    )
    inputs = "".join(f"[v{index}]" for index in range(len(sources)))
    chains.append(
        f"{inputs}xstack=inputs={len(sources)}:layout={layout}:fill=0x0b0c0e[out]"
    )
    args += [
        "-filter_complex", ";".join(chains),
        "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(out),
    ]
    result = _run(args)
    return result.returncode, result.stderr


def _scale_returning(source: Path, out: Path, width: int, height: int) -> tuple[int, str]:
    result = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0b0c0e",
            "-frames:v", "1", "-q:v", "3", str(out),
        ]
    )
    return result.returncode, result.stderr


def scale_image(source: Path, out: Path, width: int) -> None:
    _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
        ]
    )


def blank_image(out: Path, width: int, height: int) -> None:
    _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x0b0c0e:s={width}x{height}",
            "-frames:v", "1", "-q:v", "3", str(out),
        ]
    )

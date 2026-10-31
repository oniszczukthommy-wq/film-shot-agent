"""Exercise real FFmpeg binaries with a generated fixture; no API or user media."""
import subprocess

from film_shot_agent.adapters import ffmpeg


def test_real_media_pipeline_handles_unicode_paths(tmp_path):
    folder = tmp_path / 'Windows media 空格'
    folder.mkdir()
    source = folder / '源视频.mp4'
    subprocess.run([ffmpeg.ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24', '-t', '2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                   check=True, timeout=30, capture_output=True)
    info = ffmpeg.probe(source)
    assert (info.width, info.height) == (320, 180)
    assert 1900 <= info.duration_ms <= 2100
    clip = folder / '镜头.mp4'
    ffmpeg.make_clip(source, 250, 1250, clip)
    assert 900 <= ffmpeg.probe(clip).duration_ms <= 1150
    frame = folder / '预览.jpg'
    ffmpeg.extract_frame(source, .5, frame, 160)
    assert frame.read_bytes().startswith(b'\xff\xd8')
    gif = folder / '动图.gif'
    ffmpeg.make_gif(source, 0, 1000, gif, 160)
    assert gif.read_bytes().startswith(b'GIF8')
    assert len(ffmpeg.raw_rgb(source, .5)) == 64 * 36 * 3
    grid = folder / '联系表.png'
    status, error = ffmpeg.grid_images([frame, frame], grid, columns=2,
                                      cell_width=160, cell_height=90, padding=4)
    assert status == 0, error
    assert grid.read_bytes().startswith(b'\x89PNG')

#!/usr/bin/env bash
# 下载两部 CC BY 3.0 的演示影片和字幕（约 600 MB），然后建索引。
set -euo pipefail
cd "$(dirname "$0")/.."

RAW=data/library/raw
SUBS=data/library/subs
mkdir -p "$RAW" "$SUBS"

if [ ! -f "$RAW/toes_720p.mov" ]; then
  echo "· 下载 Tears of Steel (720p, 约 355 MB)"
  curl -L --progress-bar -o "$RAW/toes_720p.mov" \
    https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov
fi

if [ ! -f "$RAW/bbb_sunflower_1080p_30fps_normal.mp4" ]; then
  echo "· 下载 Big Buck Bunny (1080p, 约 263 MB)"
  curl -L --progress-bar -o "$RAW/bbb.zip" \
    https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip
  unzip -o -q "$RAW/bbb.zip" -d "$RAW" && rm -f "$RAW/bbb.zip"
fi

if [ ! -f "$SUBS/TOS-en.srt" ]; then
  echo "· 下载官方字幕"
  curl -L --silent -o "$SUBS/TOS-en.srt" \
    https://download.blender.org/demo/movies/ToS/subtitles/TOS-en.srt
  curl -L --silent -o "$SUBS/TOS-CH.srt" \
    https://download.blender.org/demo/movies/ToS/subtitles/TOS-CH.srt
fi

echo "· 建索引（抽帧 + 调色板 + 字幕，约 2 分钟）"
uv run python scripts/ingest.py

echo
echo "完成。启动："
echo "  uv run uvicorn film_shot_agent.main:app --app-dir src --port 8000"

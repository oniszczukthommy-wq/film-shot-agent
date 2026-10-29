# Shot Agent · 影视镜头与台词检索助理

一个可以现场跑起来的影视 personal agent 演示：**用一句话找画面、找台词，把结果剪成 GIF，收进参考板。**

素材全部是 **CC BY 3.0 授权**的开源电影（Blender Foundation），所以每个镜头都可以合法切片、导出、分发。

---

## 30 秒跑起来

```bash
uv sync --group dev

# 1) 把片子放进 data/library/raw/（仓库不附带，见「素材」一节）
# 2) 抽帧 + 算调色板 + 建台词索引（首次约 2 分钟）
uv run python scripts/ingest.py

# 3) 起服务
uv run uvicorn film_shot_agent.main:app --app-dir src --port 8000
```

打开 <http://localhost:8000>。

验证：

```bash
uv run pytest        # 54 个离线测试，不需要 ffmpeg、不联网
uv run ruff check .
```

---

## 它到底做了什么

### 1. 镜头库是"算"出来的，不是标出来的

没有标注团队，所以所有筛选维度都从像素里直接算：

| 维度 | 怎么来的 |
| --- | --- |
| 分镜边界 | `ffmpeg select='gt(scene,0.35)'` 检测画面突变 |
| 画幅比 | `cropdetect` 自动识别黑边内的有效画面（钢铁之泪识别出 2.397:1） |
| 调色板 | 每帧取 64×36 缩略图，k-means 聚出 5 个主色 + 各自占比 |
| 亮度 / 对比度 / 饱和度 | 同一份像素统计 |
| 冷暖倾向 | 按色相加权统计（`warm` / `cool` / `mixed` / `neutral` / `mono`） |
| 档位分桶 | 按**本库分位数**切三档，保证每个筛选项都不是空的 |

### 2. 检索状态就是 URL

```
/browse/color_temp/cool/brightness/dark
/browse/shade/3a6ea5~18~3
```

任何一次检索都能复制成链接，别人打开就是同一组结果。取色检索的三个参数是把
「目标色 + 容差 + 最小占比」直接写进路径。

### 3. 分面计数

每个筛选项旁边显示的是**"如果选它，会剩多少"**，且计算时**排除该维度自身**——
这样你才能在同一个维度里换选项，而不是看着自己被筛空。

### 4. 台词不是一句话，是有上下文的

每条命中带前一句、后一句、中文翻译、命中高亮区间，以及**说出这句话时画面是哪一帧**。
台词和镜头用时间轴自动对齐，不需要人工标。

### 5. 切片是真切片

对本地源文件用 ffmpeg 现切：MP4 或 5 档 GIF（320 → 1920 宽），带缓存，同一镜头同一格式只渲染一次。

### 6. 参考板能导出成图 / PDF

- **拼图**：`GET /api/decks/{id}/collage` — ffmpeg `xstack` 拼成一张图，按 3 列排布
- **打印 / 另存为 PDF**：`GET /decks/{id}/print` — A4 横向排版，每格带片名、年份、时间点、备注，
  页脚自动带上 CC BY 署名。用浏览器打印是因为中文字体交给浏览器渲染最稳。

### 7. Agent 是规则驱动的，而且把思考过程摊开

```
输入：找冷色调、暗一点的镜头
trace: search_shots {"color_temp":"cool","brightness":"dark"} → 31 条 / 1ms
```

模型不参与决策——面试演示必须每次都一样。规则把中文/英文的描述映射成筛选参数，
返回的 trace 面板显示每一步调了什么工具、拿到多少结果、花了多少毫秒。

---

## 架构

```
src/film_shot_agent/
├── adapters/ffmpeg.py    # 探测、场景切分、抽帧、切片、GIF（唯一碰媒体的地方）
├── services/
│   ├── look.py           # 调色板 + 亮度/对比度/饱和度/冷暖
│   ├── search.py         # 筛选、路径式查询、分面计数
│   ├── lines.py          # 台词检索 + 上下文 + 高亮 + 台词↔镜头对齐
│   ├── clips.py          # 导出与缓存
│   ├── decks.py          # 参考板
│   ├── agent.py          # 规则意图 → 工具调用 → trace
│   └── metrics.py        # 只存聚合计数，不存查询词
├── api/routes.py         # HTTP 边界
├── domain/models.py      # SQLite：Title / Shot / Cue / Deck / DeckItem / MetricEvent
└── web/                  # 单页演示前端（无构建步骤）
```

设计上的四条约束：

1. **业务只在 `services/`**，`adapters/` 不反向依赖服务层。
2. **外部进程只有 ffmpeg 一个**，且全部走固定参数、无 shell。
3. **测试不依赖 ffmpeg**：媒体调用在测试里被替换，管道逻辑仍然被覆盖。
4. **埋点只存计数器**：`agent_message`、`search_shots`… 不存查询词、不存片名。

---

## 素材与授权

| 影片 | 年份 | 授权 | 用途 |
| --- | --- | --- | --- |
| Tears of Steel | 2012 | CC BY 3.0 | 有对白 + 中英字幕，台词检索演示 |
| Big Buck Bunny | 2008 | CC BY 3.0 | 强色彩，画面检索演示 |

下载（放到 `data/library/raw/`）：

```bash
curl -o data/library/raw/toes_720p.mov \
  https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov
curl -o bbb.zip \
  https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip
unzip bbb.zip -d data/library/raw/
# 字幕
curl -o data/library/subs/TOS-en.srt https://download.blender.org/demo/movies/ToS/subtitles/TOS-en.srt
curl -o data/library/subs/TOS-CH.srt https://download.blender.org/demo/movies/ToS/subtitles/TOS-CH.srt
```

出处：© Blender Foundation | [blender.org](https://www.blender.org) — CC BY 3.0。
页面里的 `attribution` 字段会把这段署名带出来。

**不做的事**：不下载、不抓取任何未授权影视内容，不接第三方站点截图，不做 DRM/会员绕过。
切片只在本地已有的授权文件上进行。

---

## 目前不做的（也是面试时该主动说的）

| 项 | 原因 |
| --- | --- |
| 人工语义标签（景别 / 构图 / 人数 / 情绪） | 需要视觉模型或标注团队，当前只做"机器能算的"维度 |
| 向量检索（以图搜图） | 单机 SQLite + 244 镜头规模下不划算；已想清楚落地方式（见 `docs/设计取舍.md`） |
| 多人协作 / 分享链接 | 单人本机演示不需要，且整板截图外链有版权风险 |
| LLM 参与决策 | 演示要可复现；模型只适合做意图标签，不该决定返回什么 |

---

## 文档

- [`docs/设计取舍.md`](docs/设计取舍.md) — 为什么这么做，以及借了什么、没借什么
- [`docs/面试讲解.md`](docs/面试讲解.md) — 90 秒演示脚本 + 常见追问

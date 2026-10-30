# Shot Agent · 影视镜头检索 + 问片助理

一个可以现场跑起来的影视 personal agent：**问一部片，给你能核对的答案；用一句话找画面、找台词，把结果剪成 GIF，收进参考板。**

- **问片**（`/chat`）：一个对话框，给一句台词找电影/时间点/片段；也能找片、查评分/口碑、认镜头。联网搜索 + 33 台词字幕库，评分和观看链接带来源。
- **镜头库**（`/`）：两部 CC BY 3.0 开源电影的 244 个镜头，可筛选、播放、切片、导出参考板。

镜头素材全部是 **CC BY 3.0 授权**的开源电影（Blender Foundation），所以每个镜头都可以合法切片、导出、分发。

---

## 30 秒跑起来

```bash
git clone https://github.com/oniszczukthommy-wq/film-shot-agent && cd film-shot-agent
cp .env.example .env        # 填模型 Key（必填）和 TMDB Key（强烈建议）
uv sync --group dev
uv run uvicorn film_shot_agent.main:app --app-dir src --port 8000
```

打开 <http://localhost:8000/chat>（问片）或 <http://localhost:8000>（镜头库）。旧入口 `/ask` 会跳转到 `/chat`。

**公网演示**：<https://film-shot-agent.onrender.com/chat>（Render 免费实例，线上不含影片本体；详见 [`docs/上线说明.md`](docs/上线说明.md)）。

`.env` 三组配置：

| 变量 | 作用 | 不填会怎样 |
| --- | --- | --- |
| `FILM_AGENT_LLM_API_KEY` / `_BASE_URL` / `_MODEL` | 问片的模型，OpenAI 兼容接口 | `/chat` 返回 503，镜头库照常 |
| `FILM_AGENT_TMDB_API_KEY` | 结构化评分、评论、合法观看渠道（免费优先） | 只能靠搜索摘要，评分可能显示不出来 |
| `FILM_AGENT_SEARCH_API_KEY` / `_PROVIDER` | Tavily / Brave | 用 DuckDuckGo + 360 免费兜底，偶尔会被限流 |

仓库里带了**预置索引**（`data/library/demo.sqlite3` + 244 张缩略图，约 6 MB），
所以 clone 下来就能直接浏览、检索、看板；播放和切片需要影片本体，跑一次：

```bash
./scripts/fetch_demo.sh   # 下载两部 CC BY 影片 + 字幕，重建索引（约 10 分钟，含 620 MB 下载）
```

脚本会新建 `film.sqlite3`，**不会覆盖**仓库里的 `demo.sqlite3`；
之后应用优先读 `film.sqlite3`，没有时才回落到 demo 索引。

自己换片子也一样：丢进 `data/library/raw/`，改 `scripts/ingest.py` 里的 `FILMS`，再跑一次 ingest。

验证：

```bash
uv run pytest        # 111 个离线测试，不需要 ffmpeg、不联网
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

### 6. 能看片，而且是从这一镜开始

- `GET /media/video/{slug}` 直出本地 MP4，Starlette 原生支持 **Range**（`206 Partial Content`），进度条能拖
- 点镜头卡片「播放」，弹窗里的播放器**直接定位到这一镜的起始时间**，静帧和画面像素级对得上
- 每条台词后面的「▶ 从这句开始播」直接跳到那句话的时间点
- **J / K / L** 逐帧后退 / 播放暂停 / 逐帧前进（和两家参考产品的剪辑器同一套键位）

播放读的是 `data/library/web/{slug}.mp4`（ingest 时用 `-c:v copy` 转封装成浏览器友好的 MP4，
几秒钟，不动画质）；找不到才回落到原始文件。

### 7. 参考板能导出成图 / PDF

- **拼图**：`GET /api/decks/{id}/collage` — ffmpeg `xstack` 拼成一张图，按 3 列排布
- **打印 / 另存为 PDF**：`GET /decks/{id}/print` — A4 横向排版，每格带片名、年份、时间点、备注，
  页脚自动带上 CC BY 署名。用浏览器打印是因为中文字体交给浏览器渲染最稳。

### 8. Agent 是规则驱动的，而且把思考过程摊开

```
输入：找冷色调、暗一点的镜头
trace: search_shots {"color_temp":"cool","brightness":"dark"} → 31 条 / 1ms
```

模型不参与决策——面试演示必须每次都一样。规则把中文/英文的描述映射成筛选参数，
返回的 trace 面板显示每一步调了什么工具、拿到多少结果、花了多少毫秒。

---

## 问片是怎么做到"能核对"的

`/chat` 不是让模型直接背书，而是一个**研究循环**：

```
问题 → 模型决定调哪个工具 → 执行 → 证据回填 → 再决定 → 整理成 JSON
```

工具只有七个：

| 工具 | 做什么 | 证据长什么样 |
| --- | --- | --- |
| `search_web` | 联网搜索 | 标题 + URL + 摘要 |
| `movie_facts` | TMDB 查年份/评分/评论/观看渠道 | 结构化字段 |
| `where_to_watch` | 找合法平台，免费优先 | 平台 + 免费/会员/付费 + 链接 |
| `reviews` | 豆瓣 / IMDb / 烂番茄摘要 | 来源 + 摘要 + 链接 |
| `search_subtitles` | 33 台词字幕库查一句台词（中/英字幕索引） | 片名 + 精确时间点 + 双语原句 + 前后句 + 海报 + 豆瓣分 |
| `search_quote` | 台词找电影，先查字幕库和本地片库 | 时间点 + 镜头 + 网页结果 |
| `identify_scene` | 模糊画面描述找电影 | 多个候选线索 |

三道硬约束，都是确定性代码，不靠模型自觉：

1. **引用白名单**：最终答案里的 URL 必须是工具这次真的返回过的，模型自己编的链接会被丢掉。
2. **评分反查**：评分必须能在对应来源的摘要里找到数字；豆瓣/IMDb 之外的博客转述不算评分。
3. **观看渠道反查**：平台和"免费/会员"标签只能用工具记录过的那份，模型不能自己改；搜索推断的免费只能写「可能免费」。

所以它会给候选、给证据、给置信度，也会说"没查到"。它不会为了好看编一个豆瓣分。

### 33 台词字幕库

`search_subtitles` 直接调用 [33 台词](https://app.33tc.net/) 的公开搜索（`langType=0` 英文字幕、`langType=1` 中文字幕），
用来补上"一句台词→哪部片、第几分钟"这一步。它返回片名、精确时间点、原句、中文翻译、前后句、海报和收录的豆瓣分。

- 没有官方 API，也没有 Key；用的是它网页自己的搜索接口。它变了或挂了，代码会记录一条 caveat 并回落到 Tavily/本地片库，不会让回答失败。
- 只在个人研究场景下一次查一句，不批量抓取、不落地字幕库、不暴露视频地址；片段与版权归原片方。
- 想关掉：`FILM_AGENT_SUBTITLE_SEARCH=0`。

### 边界（这也是产品的一部分）

| 你要的 | 现在能做到 | 为什么 |
| --- | --- | --- |
| 找片 + 免费优先 | ✅ | TMDB 的 JustWatch 数据分 free/ads/flatrate/rent/buy；没有 TMDB 时用搜索结果里的官方内容页兜底（免费只能标「可能免费」） |
| 评分 + 观众评价 | ✅（有 TMDB Key 时最稳） | 豆瓣没有公开 API，只引用搜索摘要 + 豆瓣页面链接，不抓取 |
| 台词找电影 | ✅ | 33 台词字幕库能给片名、精确时间点和双语原句；库外台词回落到联网搜索，只给候选和出处，不编时间点 |
| 模糊镜头找电影 | ⚠️ 只给候选 | 没有全电影镜头库；文字描述是研究题，不是唯一解。截图识别在二期 |
| 不碰盗版 | ✅ | 观看链接有平台白名单，网盘/磁力/种子不会出现 |

---

## 架构

```
src/film_shot_agent/
├── adapters/ffmpeg.py    # 探测、场景切分、抽帧、切片、GIF（唯一碰媒体的地方）
├── adapters/search.py    # DuckDuckGo / 360 / Tavily / Brave
├── adapters/llm.py       # OpenAI 兼容 chat + tool calling
├── adapters/tmdb.py      # 评分、评论、JustWatch 观看渠道
├── adapters/thirtythree.py # 33 台词字幕库（无 Key，个人研究用；失败自动回落）
├── services/
│   ├── look.py           # 调色板 + 亮度/对比度/饱和度/冷暖
│   ├── search.py         # 筛选、路径式查询、分面计数
│   ├── lines.py          # 台词检索 + 上下文 + 高亮 + 台词↔镜头对齐
│   ├── clips.py          # 导出与缓存
│   ├── decks.py          # 参考板
│   ├── agent.py          # 本地规则意图 → 工具调用 → trace
│   ├── research.py       # 问片：研究循环 + 证据白名单 + JSON 整理
│   └── metrics.py        # 只存聚合计数，不存查询词
├── api/routes.py         # HTTP 边界
├── domain/models.py      # SQLite：Title / Shot / Cue / Deck / DeckItem / MetricEvent
└── web/                  # 镜头库 + 问片前端（无构建步骤）
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
| 转码 / HLS / 远程流 | 文件就在本地，直出 + Range 就够；转码只用在导出 GIF |
| LLM 参与本地镜头检索 | 本地筛选仍是规则驱动，结果可复现；问片层才让模型编排工具 |
| 自动抓取豆瓣页面 | 没有公开 API，抓取违反条款且不稳定；只引用搜索摘要和跳转链接 |
| 截图/以图搜片 | 需要视觉模型 + 以图搜图接口，先验证准确率和成本再做 |

---

## 文档

- [`docs/问片设计.md`](docs/问片设计.md) — 问片层：工具、证据闸门、边界、下一步
- [`docs/问片验收-第1轮.md`](docs/问片验收-第1轮.md) — 第一轮 10 条真实问题的结果与修复
- [`docs/问片验收-第2轮.md`](docs/问片验收-第2轮.md) — 第二轮 10 条：9 命中 / 1 部分 / 0 错误，平均 52 秒
- [`docs/问片验收-第3轮.md`](docs/问片验收-第3轮.md) — 接入 33 台词字幕库：给台词直接出片名 + 时间点 + 双语台词 + 海报
- [`docs/设计取舍.md`](docs/设计取舍.md) — 为什么这么做，以及借了什么、没借什么
- [`docs/后端自查.md`](docs/后端自查.md) — 全路由 + 恶意输入 + 并发走查，已知边界都在这里
- [`docs/面试讲解.md`](docs/面试讲解.md) — 90 秒演示脚本 + 常见追问

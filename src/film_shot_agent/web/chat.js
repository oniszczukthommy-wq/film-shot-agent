/* One-dialog film agent. All model output is text nodes; links are backend-vetted. */

const STORAGE_KEY = "film-shot-agent-chat-v2";
const MAX_MESSAGES = 12;
const SUGGESTS = [
  "这句台词“我看过你们人类……”是哪部片的？",
  "“说好的一辈子，差一年一个月一天一个时辰，都不算一辈子”是哪部电影？",
  "哪部电影里男主角在雨中跳舞？",
  "《周处除三害》值得看吗，在哪看？",
  "Is Oppenheimer worth watching? Ratings and streaming?",
  "推荐一部 90 分钟以内、适合周五晚上看的喜剧",
];
const INTENT_LABEL = {
  discover: "找片",
  rating: "口碑",
  watch: "在哪看",
  scene: "认镜头",
  quote: "找台词",
  mixed: "综合",
  other: "回答",
};

const $ = (selector) => document.querySelector(selector);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function outbound(href, text, cls = "") {
  const url = safeUrl(href);
  if (!url) return el("span", { class: cls }, text);
  return el("a", { class: cls, href: url, target: "_blank", rel: "noopener noreferrer" }, text);
}

function confidenceLabel(value) {
  if (value === "high") return "置信度 高";
  if (value === "low") return "置信度 低";
  return "置信度 中";
}

function accessClass(label) {
  if (!label) return "";
  if (label.includes("广告")) return "ads";
  if (label.includes("免费")) return "free";
  if (label.includes("会员") || label.includes("付费")) return "paid";
  return "";
}

function answerCard(data) {
  const intent = INTENT_LABEL[data.intent] || "回答";
  const card = el("section", { class: "ask-answer-card chat-answer" },
    el("div", { class: "ask-answer-head" },
      el("span", { class: "ask-tag strong" }, intent),
      el("span", { class: "ask-tag" }, "答案可核对"),
    ),
    el("p", { class: "ask-answer-text" }, data.answer || ""),
  );
  if (data.engine) {
    card.append(
      el("div", { class: "ask-engine" },
        el("span", {}, `模型 ${data.engine.model || "—"}`),
        el("span", {}, `搜索 ${data.engine.search || "—"}`),
        el("span", {}, data.engine.tmdb ? "TMDB 已连接" : "TMDB 未配置"),
        el("span", {}, `${data.usage?.steps ?? 0} 步 · ${data.usage?.completion_tokens ?? 0} tokens`),
      ),
    );
  }
  return card;
}

function ratingChip(item) {
  const inner = [
    el("small", {}, item.source || "评分"),
    el("b", {}, item.score || "—"),
    el("span", {}, item.out_of ? `/ ${item.out_of}` : ""),
  ];
  if (item.note) inner.push(el("small", {}, item.note));
  if (item.url) {
    const link = outbound(item.url, "", "rating");
    link.append(...inner);
    return link;
  }
  return el("span", { class: "rating" }, ...inner);
}

function watchRow(item) {
  const direct = Boolean(item.direct);
  return el("div", { class: "watch-row" },
    el("span", { class: `access ${direct ? "direct" : "search"}` }, direct ? "直接播放" : "平台搜索"),
    el("span", { class: "name" }, item.platform || "平台"),
    el("span", { class: `access ${accessClass(item.access)}` }, item.access || "需确认"),
    el("span", { class: "note" }, item.note || ""),
    outbound(item.url, "打开 ↗"),
  );
}

function sceneBlock(scene) {
  if (!scene || (!scene.quote && !scene.line && !scene.description && !scene.clip_url && !scene.source_url)) return null;
  const block = el("div", { class: "film-block scene-block" },
    el("h4", {}, "台词 / 场景"),
  );
  if (scene.quote) block.append(el("blockquote", { class: "scene-quote" }, `「${scene.quote}」`));
  if (scene.line && scene.line !== scene.quote) {
    block.append(el("p", { class: "scene-original" }, scene.line));
  }
  if (scene.line_zh && scene.line_zh !== scene.quote) {
    block.append(el("p", { class: "scene-zh" }, scene.line_zh));
  }
  const meta = el("div", { class: "scene-meta" });
  if (scene.character) meta.append(el("span", {}, `角色：${scene.character}`));
  if (scene.timecode) meta.append(el("span", { class: "scene-time" }, `约 ${scene.timecode}`));
  if (scene.clip_platform) meta.append(el("span", {}, `候选片段：${scene.clip_platform}`));
  if (scene.source_url) meta.append(el("span", {}, `时间点来源：${scene.source_label || "33 台词"}`));
  meta.append(el("span", { class: `conf ${scene.confidence || "medium"}` }, confidenceLabel(scene.confidence)));
  block.append(meta);
  if (scene.description) block.append(el("p", { class: "scene-desc" }, scene.description));
  const actions = el("div", { class: "scene-actions" });
  if (scene.subtitle_id) {
    actions.append(
      el("button", { class: "btn btn-sm btn-quiet", type: "button", onclick: () => openContext(scene) }, "看前后文"),
    );
  }
  if (scene.clip_url) actions.append(outbound(scene.clip_url, "看候选片段 ↗", "btn btn-sm"));
  if (scene.source_url) actions.append(outbound(scene.source_url, "在 33 台词看这一句 ↗", "btn btn-sm btn-quiet"));
  if (actions.childElementCount) block.append(actions);
  else block.append(el("p", { class: "hint" }, "暂无可核对的片段；时间点和平台跳转仅供参考。"));
  return block;
}

function closeContext() {
  document.querySelector(".context-overlay")?.remove();
  document.body.style.overflow = "";
}

async function openContext(scene) {
  closeContext();
  const overlay = el("div", { class: "context-overlay", role: "dialog", "aria-modal": "true", "aria-label": "台词前后文" });
  const panel = el("section", { class: "context-panel" });
  panel.append(
    el("div", { class: "context-head" },
      el("div", {},
        el("h3", {}, "台词前后文"),
        el("p", { class: "context-sub" }, [scene.timecode ? `约 ${scene.timecode}` : "", scene.source_label || "33 台词"].filter(Boolean).join(" · ")),
      ),
      el("button", { class: "context-close", type: "button", "aria-label": "关闭", onclick: closeContext }, "×"),
    ),
  );
  const list = el("div", { class: "context-list" }, el("p", { class: "context-loading" }, "正在读取字幕…"));
  panel.append(list);
  overlay.append(panel);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeContext();
  });
  document.addEventListener("keydown", function onKey(event) {
    if (event.key === "Escape") {
      closeContext();
      document.removeEventListener("keydown", onKey);
    }
  });
  document.body.append(overlay);
  document.body.style.overflow = "hidden";

  try {
    const response = await fetch(`/api/chat/subtitles/${scene.subtitle_id}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error?.message || "字幕读取失败");
    list.replaceChildren();
    for (const item of data.items || []) {
      const active = item.id === scene.subtitle_id;
      list.append(
        el("div", { class: `context-line${active ? " active" : ""}` },
          el("span", { class: "context-time" }, item.start_time || ""),
          el("div", { class: "context-copy" },
            item.content ? el("p", { class: "context-text" }, item.content) : null,
            item.content_zh ? el("p", { class: "context-zh" }, item.content_zh) : null,
          ),
        ),
      );
    }
    if (!list.childElementCount) list.append(el("p", { class: "context-loading" }, "没有拿到前后文。"));
  } catch (error) {
    list.replaceChildren(el("p", { class: "context-loading" }, error.message || "字幕读取失败，请稍后再试。"));
  }
}

function filmCard(title) {
  const body = el("div", { class: "film-body" });
  const sub = [title.original_name, title.year, title.kind].filter(Boolean).join(" · ");
  body.append(
    el("div", { class: "film-head" },
      el("div", {},
        el("h3", { class: "film-name" }, title.name || "未命名"),
        sub ? el("p", { class: "film-sub" }, sub) : null,
      ),
      el("span", { class: `conf ${title.confidence || "medium"}` }, confidenceLabel(title.confidence)),
    ),
  );

  if (title.ratings?.length) {
    const row = el("div", { class: "rating-row" });
    for (const item of title.ratings) row.append(ratingChip(item));
    body.append(row);
  }

  const scene = sceneBlock(title.scene);
  if (scene) body.append(scene);

  if (title.watch?.length) {
    const block = el("div", { class: "film-block" },
      el("h4", {}, "在哪看 · 直接播放优先，其余为平台搜索"),
    );
    const direct = title.watch.filter((item) => item.direct);
    const search = title.watch.filter((item) => !item.direct);
    if (direct.length) {
      const list = el("div", { class: "watch-list" });
      for (const item of direct) list.append(watchRow(item));
      block.append(list);
    }
    if (search.length) {
      const chips = el("div", { class: "platform-chips" });
      for (const item of search) {
        const link = outbound(item.url, item.platform || "平台搜索");
        link.classList.add("platform-chip");
        link.title = item.note || "平台搜索页，不是直接播放页";
        chips.append(link);
      }
      block.append(
        el("p", { class: "watch-search-label" }, "平台搜索（不是直接播放，需自己确认）"),
        chips,
      );
    }
    body.append(block);
  }

  if (title.reviews?.length) {
    const block = el("div", { class: "film-block" }, el("h4", {}, "观众评价"));
    for (const review of title.reviews) {
      block.append(
        el("div", { class: "review" },
          el("p", {}, review.summary || ""),
          el("div", { class: "src" },
            el("b", {}, review.source || "网页摘要"),
            review.url ? outbound(review.url, "查看来源 →") : null,
          ),
        ),
      );
    }
    body.append(block);
  }

  if (title.evidence?.length) {
    const list = el("ul", { class: "evidence" });
    for (const line of title.evidence) list.append(el("li", {}, line));
    body.append(list);
  }

  const poster = safeUrl(title.poster);
  const media = poster
    ? el("img", {
        class: "film-poster",
        src: poster,
        alt: `${title.name} 海报`,
        loading: "lazy",
        referrerPolicy: "no-referrer",
      })
    : el("div", { class: "film-no-poster" }, "暂无海报");
  return el("article", { class: "film-card" }, media, body);
}

function titlesSection(titles) {
  const section = el("section", { class: "ask-section" },
    el("div", { class: "ask-section-title" },
      el("h2", {}, "候选"),
      el("span", {}, "按置信度排序，点开来源核对"),
    ),
  );
  const list = el("div", { class: "film-list" });
  for (const title of titles) list.append(filmCard(title));
  section.append(list);
  return section;
}

function citationsSection(citations) {
  const section = el("section", { class: "ask-section" },
    el("div", { class: "ask-section-title" },
      el("h2", {}, "来源"),
      el("span", {}, "助理这次实际打开过的页面"),
    ),
  );
  const grid = el("div", { class: "ask-citations" });
  citations.forEach((item, index) => {
    const link = outbound(item.url, "");
    if (!link.getAttribute("href")) return;
    link.classList.add("ask-citation");
    link.replaceChildren(
      el("small", {}, String(index + 1).padStart(2, "0")),
      document.createTextNode(item.title || item.url),
    );
    grid.append(link);
  });
  section.append(grid);
  return section;
}

function caveatsSection(caveats) {
  const list = el("ul", {});
  for (const line of caveats) list.append(el("li", {}, line));
  return el("section", { class: "ask-section ask-caveats" }, el("h3", {}, "注意"), list);
}

function traceSection(trace) {
  const rows = trace.map((step) => el("tr", {},
    el("td", {}, el("code", {}, step.tool || "")),
    el("td", {}, el("code", {}, JSON.stringify(step.args || {}).slice(0, 120))),
    el("td", {}, String(step.count ?? 0)),
    el("td", {}, `${step.ms ?? 0}ms`),
  ));
  return el("details", { class: "ask-trace" },
    el("summary", {}, `助理调用了 ${trace.length} 次工具（点开看 trace）`),
    el("table", { class: "ask-trace-table" },
      el("thead", {}, el("tr", {},
        el("th", {}, "工具"), el("th", {}, "参数"), el("th", {}, "结果"), el("th", {}, "耗时"),
      )),
      el("tbody", {}, ...rows),
    ),
  );
}

function followupsSection(followups) {
  const row = el("div", { class: "ask-followups" });
  for (const text of followups) row.append(el("button", { onclick: () => send(text) }, text));
  return row;
}

function assistantBody(data) {
  const wrap = el("div", { class: "chat-assistant" }, answerCard(data));
  if (data.titles?.length) wrap.append(titlesSection(data.titles));
  if (data.citations?.length) wrap.append(citationsSection(data.citations));
  if (data.caveats?.length) wrap.append(caveatsSection(data.caveats));
  if (data.trace?.length) wrap.append(traceSection(data.trace));
  if (data.followups?.length) wrap.append(followupsSection(data.followups));
  return wrap;
}

function renderMessage(message) {
  if (message.role === "user") {
    return el("div", { class: "chat-row user" },
      el("div", { class: "chat-bubble" }, message.content),
    );
  }
  const row = el("div", { class: "chat-row assistant" });
  if (message.data) row.append(assistantBody(message.data));
  else if (message.error) row.append(el("div", { class: "chat-error" }, message.content));
  else row.append(el("div", { class: "chat-assistant" }, el("p", {}, message.content)));
  return row;
}

function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function renderAll() {
  const thread = $("#thread");
  thread.replaceChildren(...state.messages.map(renderMessage));
  document.body.classList.toggle("chatting", state.messages.length > 0);
  const intro = $("#intro");
  if (intro) intro.hidden = state.messages.length > 0;
  if (state.messages.length) scrollToBottom();
}

function save() {
  const trimmed = state.messages.slice(-MAX_MESSAGES);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    /* storage full or private mode; chat still works in memory */
  }
}

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const rows = raw ? JSON.parse(raw) : [];
    if (Array.isArray(rows)) {
      state.messages = rows.filter((row) => row && (row.role === "user" || row.role === "assistant"));
    }
  } catch {
    state.messages = [];
  }
}

function setBusy(busy) {
  state.busy = busy;
  $("#send").disabled = busy;
  $("#chat-input").disabled = busy;
  $("#send").textContent = busy ? "查询中…" : "发送";
}

function showLoading() {
  const thread = $("#thread");
  const row = el("div", { class: "chat-row assistant", id: "chat-loading" },
    el("div", { class: "chat-assistant chat-loading" },
      el("div", { class: "ask-loading-bar" }, el("i", {})),
      el("p", { class: "hint" }, "联网搜索 → 核对评分/台词 → 整理来源。通常 10–30 秒。"),
    ),
  );
  thread.append(row);
  scrollToBottom();
}

async function send(text) {
  const query = String(text || "").trim();
  if (!query || state.busy) return;
  const history = state.messages
    .filter((row) => row.role === "user" || (row.role === "assistant" && !row.error))
    .slice(-6)
    .map((row) => ({ role: row.role, content: row.content }));
  state.messages.push({ role: "user", content: query });
  renderAll();
  $("#chat-input").value = "";
  setBusy(true);
  showLoading();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000);
    let response;
    try {
      response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query, history }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    $("#chat-loading")?.remove();
    if (!response.ok) {
      state.messages.push({
        role: "assistant",
        content: payload?.error?.message || `问片失败（HTTP ${response.status}）。`,
        error: true,
      });
    } else {
      state.messages.push({ role: "assistant", content: payload.answer || "", data: payload });
    }
  } catch (error) {
    $("#chat-loading")?.remove();
    state.messages.push({
      role: "assistant",
      content: error?.name === "AbortError" ? "查询超时了，可以拆成更小的问题再试。" : "网络或服务暂时不可用，请稍后再试。",
      error: true,
    });
  } finally {
    setBusy(false);
    renderAll();
    save();
    $("#chat-input").focus();
  }
}

function newChat() {
  state.messages = [];
  localStorage.removeItem(STORAGE_KEY);
  renderAll();
  $("#intro").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("#chat-input").focus();
}

function boot() {
  const suggestions = $("#suggestions");
  for (const text of SUGGESTS) {
    suggestions.append(el("button", { class: "chip", onclick: () => send(text) }, text));
  }
  $("#composer").addEventListener("submit", (event) => {
    event.preventDefault();
    send($("#chat-input").value);
  });
  $("#new-chat").addEventListener("click", newChat);
  fetch("/api/chat/meta")
    .then((response) => response.json())
    .then((data) => {
      if (!data.enabled) {
        $("#engine-stat").textContent = "模型未配置";
        return;
      }
      $("#engine-stat").textContent = `联网搜索 · ${data.model || "已连接"}`;
    })
    .catch(() => {});
  load();
  renderAll();
  $("#intro").hidden = state.messages.length > 0;
  $("#chat-input").focus();
}

const state = { messages: [], busy: false };
boot();

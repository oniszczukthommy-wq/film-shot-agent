const DIMENSIONS = ["title", "color_temp", "brightness", "contrast", "saturation", "aspect", "resolution", "length"];
const DIM_LABELS = {
  title: "影片", color_temp: "色调", brightness: "亮度", contrast: "对比度",
  saturation: "饱和度", aspect: "画幅", resolution: "分辨率", length: "镜头长",
};

const state = {
  view: "agent",
  filters: {},
  shade: null,
  distance: 8,
  proportion: 3,
  sort: "relevance",
  offset: 0,
  limit: 36,
  agent: null,
  decks: [],
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};
const fmt = (ms) => {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return m ? `${m}:${String(s % 60).padStart(2, "0")}` : `0:${String(s).padStart(2, "0")}`;
};
let toastTimer;
function toast(text) {
  const node = $("#toast");
  node.textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2200);
}

function queryString(extra = {}) {
  const params = new URLSearchParams();
  for (const key of DIMENSIONS) if (state.filters[key]) params.set(key, state.filters[key]);
  if (state.shade) {
    params.set("shade", state.shade.replace("#", ""));
    params.set("distance", state.distance);
    params.set("proportion", state.proportion);
  }
  if (state.sort !== "relevance") params.set("sort", state.sort);
  params.set("limit", state.limit);
  params.set("offset", state.offset);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  return params.toString();
}

function pathString() {
  const parts = [];
  for (const key of DIMENSIONS) if (state.filters[key]) parts.push(key, encodeURIComponent(state.filters[key]));
  if (state.shade) parts.push("shade", `${state.shade.replace("#", "")}~${state.distance}~${state.proportion}`);
  if (state.sort !== "relevance") parts.push("sort", state.sort);
  return parts.length ? `/browse/${parts.join("/")}` : "/browse";
}

function syncUrl() {
  history.replaceState(null, "", state.view === "agent" ? "/" : pathString());
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.text()).slice(0, 200));
  return response.json();
}

/* ---------------- facets ---------------- */

async function loadFacets() {
  const data = await api(`/api/facets?${queryString()}`);
  const rail = $("#facets");
  rail.replaceChildren();
  for (const key of DIMENSIONS) {
    const values = data.facets[key] || [];
    if (!values.length) continue;
    rail.append(el("h3", {}, DIM_LABELS[key] || key));
    const box = el("div", { class: "facet" });
    for (const item of values.slice(0, 14)) {
      box.append(
        el("button", {
          "aria-pressed": String(item.selected),
          onclick: () => toggle(key, item.value),
          title: `${DIM_LABELS[key]}: ${item.label}`,
        }, el("span", {}, item.label), el("span", { class: "num" }, item.count))
      );
    }
    rail.append(box);
  }
}

function toggle(key, value) {
  state.filters[key] = state.filters[key] === value ? null : value;
  state.offset = 0;
  render();
}

/* ---------------- shots ---------------- */

async function loadShots() {
  const data = await api(`/api/shots?${queryString()}`);
  const view = $("#view");
  view.replaceChildren();
  view.append(
    el("div", { class: "result-head" },
      el("h2", {}, state.agentActive ? "助理结果" : "镜头检索"),
      el("span", { class: "count" }, `${data.total} 个镜头`),
      el("span", { class: "path" }, data.path),
      el("select", {
        class: "sort",
        onchange: (event) => { state.sort = event.target.value; state.offset = 0; render(); },
      }, ...Object.entries({ relevance: "默认", time: "时间顺序", bright: "由亮到暗", dark: "由暗到亮", long: "长镜头优先" })
        .map(([value, label]) => el("option", { value, selected: state.sort === value }, label)))
    )
  );

  if (!data.items.length) {
    view.append(el("div", { class: "empty" }, "这个组合没有镜头。试试放宽条件，或清空筛选。"));
    return;
  }
  const grid = el("div", { class: "grid" });
  for (const shot of data.items) grid.append(shotCard(shot));
  view.append(grid);
  if (data.total > data.items.length) {
    const more = el("div", { class: "rail-actions", style: "max-width:280px;margin:22px auto 0" },
      el("button", { onclick: () => { state.offset += state.limit; loadShots(); } }, `再看 ${Math.min(state.limit, data.total - data.items.length)} 个`));
    view.append(more);
  }
}

function paletteBar(swatches) {
  const bar = el("div", { class: "palette" });
  for (const swatch of swatches.slice(0, 6)) {
    bar.append(el("i", { style: `background:#${swatch.hex.replace("#", "")}`, title: `${swatch.hex} ${(swatch.weight * 100).toFixed(0)}%` }));
  }
  return bar;
}

function shotCard(shot) {
  const card = el("article", { class: "shot" });
  card.append(
    el("div", { class: "shot-img", onclick: () => openShot(shot.id) },
      el("img", { src: `/media/thumbs/${shot.thumb}`, loading: "lazy", alt: "" }),
      el("span", { class: "shot-badge" }, fmt(shot.start_ms))
    ),
    paletteBar(shot.look.palette),
    el("div", { class: "shot-body" },
      el("div", { class: "shot-title" }, el("b", {}, shot.title), el("span", {}, shot.year || "")),
      el("div", { class: "shot-meta" },
        `${shot.look.color_temp_label} · ${shot.aspect_ratio}:1 · ${shot.look.brightness_bucket === "dark" ? "暗" : shot.look.brightness_bucket === "bright" ? "亮" : "中"} · ${shot.look.saturation_bucket}`),
      el("div", { class: "shot-actions" },
        el("button", { onclick: () => openShot(shot.id) }, "播放"),
        el("button", { onclick: () => exportClip(shot.id, "gif-s") }, "GIF"),
        el("button", { onclick: () => addToDeck("shot", shot.id) }, "加入板"))
    )
  );
  return card;
}

async function openShot(id) {
  const shot = await api(`/api/shots/${id}`);
  const modal = $("#modal-body");
  modal.replaceChildren(
    playerBlock(shot.title_slug, shot.start_ms, `${shot.title} · ${fmt(shot.start_ms)}`),
    el("div", { class: "modal-body" },
      el("div", {},
        paletteBar(shot.look.palette),
        el("dl", { class: "kv", style: "margin-top:14px" },
          el("dt", {}, "影片"), el("dd", {}, `${shot.title} (${shot.year})`),
          el("dt", {}, "时间点"), el("dd", {}, `${fmt(shot.start_ms)} – ${fmt(shot.end_ms)}`),
          el("dt", {}, "画幅"), el("dd", {}, `${shot.aspect_ratio}:1 · ${shot.resolution}`),
          el("dt", {}, "亮度"), el("dd", {}, `${shot.look.brightness.toFixed(2)} (${shot.look.brightness_bucket})`),
          el("dt", {}, "对比度"), el("dd", {}, `${shot.look.contrast.toFixed(2)} (${shot.look.contrast_bucket})`),
          el("dt", {}, "饱和度"), el("dd", {}, `${shot.look.saturation.toFixed(2)} (${shot.look.saturation_bucket})`),
          el("dt", {}, "色调"), el("dd", {}, shot.look.color_temp_label),
          el("dt", {}, "调色板"), el("dd", {}, shot.look.palette.map((s) => `#${s.hex.replace("#", "")} ${(s.weight * 100).toFixed(0)}%`).join("  "))
        ),
        el("p", { class: "hint", style: "margin-top:12px" }, shot.title_attribution || "")
      ),
      el("div", {},
        el("div", { class: "hint" }, "导出这一段"),
        el("div", { class: "export" },
          el("button", { onclick: () => exportClip(shot.id, "mp4") }, "MP4"),
          ...["xs", "s", "m", "l", "xl"].map((size) =>
            el("button", { onclick: () => exportClip(shot.id, `gif-${size}`) }, `GIF ${size.toUpperCase()}`)),
          el("button", { onclick: () => addToDeck("shot", shot.id) }, "加入参考板")
        ),
        el("div", { class: "hint", style: "margin-top:14px" }, "镜头切自影片原始文件，导出结果为本地生成。"))
    )
  );
  $("#modal").classList.add("open");
  bindPlayerKeys();
}

function playerBlock(slug, startMs, label) {
  const wrap = el("div", { class: "player" },
    el("video", {
      id: "player",
      controls: "controls",
      preload: "metadata",
      playsinline: "playsinline",
      src: `/media/video/${slug}`,
    }),
    el("div", { class: "player-bar" },
      el("span", { class: "player-label" }, label),
      el("span", { class: "hint" }, "J/K/L 逐帧 / 播放暂停 · 空格播放"))
  );
  const video = wrap.querySelector("video");
  video.addEventListener("loadedmetadata", () => {
    if (Number.isFinite(startMs)) video.currentTime = Math.max(0, startMs / 1000);
  });
  return wrap;
}

function bindPlayerKeys() {
  const video = document.getElementById("player");
  if (!video) return;
  const onKey = (event) => {
    if (event.target.matches("input, textarea")) return;
    const step = 1 / 25;
    if (event.key === "k" || event.code === "Space") {
      event.preventDefault();
      video.paused ? video.play() : video.pause();
    } else if (event.key === "l") {
      video.currentTime = Math.min(video.duration || 0, video.currentTime + step);
    } else if (event.key === "j") {
      video.currentTime = Math.max(0, video.currentTime - step);
    }
  };
  document.addEventListener("keydown", onKey);
  $("#modal-close").addEventListener("click", () => document.removeEventListener("keydown", onKey));
}

async function openPlayerAt(slug, startMs, label) {
  const modal = $("#modal-body");
  modal.replaceChildren(playerBlock(slug, startMs, label));
  $("#modal").classList.add("open");
  bindPlayerKeys();
}

async function exportClip(id, fmt) {
  toast(`正在用 ffmpeg 导出 ${fmt.toUpperCase()}…`);
  const link = document.createElement("a");
  link.href = `/api/shots/${id}/clip?fmt=${fmt}`;
  link.target = "_blank";
  link.rel = "noopener";
  link.click();
  toast("导出完成，已在新标签打开");
}

/* ---------------- lines ---------------- */

async function loadLines(keyword) {
  state.lastKeyword = keyword;
  const params = new URLSearchParams({ q: keyword || "" });
  if (state.filters.title) params.set("title", state.filters.title);
  const data = await api(`/api/lines?${params}`);
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" },
      el("h2", {}, "台词检索"),
      el("span", { class: "count" }, `${data.total} 条`),
      el("span", { class: "path" }, keyword ? `关键词「${keyword}」` : "输入关键词开始")),
    el("form", { class: "agent-form", style: "margin-bottom:18px", onsubmit: (event) => { event.preventDefault(); loadLines(event.target.q.value.trim()); } },
      el("input", { class: "agent-input", name: "q", value: keyword || "", placeholder: "搜台词原文或中文翻译，例如 robot、freaked out、机器人" }),
      el("button", { class: "agent-send", type: "submit" }, "搜台词"))
  );
  if (!keyword) return;
  if (!data.items.length) {
    view.append(el("div", { class: "empty" }, "没有匹配的台词。试试更短的词。"));
    return;
  }
  const list = el("div", { class: "lines" });
  for (const item of data.items) list.append(lineCard(item));
  view.append(list);
}

function marked(text, spans) {
  if (!spans || !spans.length) return document.createTextNode(text);
  const node = document.createElement("span");
  let cursor = 0;
  for (const [start, end] of spans) {
    if (start > cursor) node.append(text.slice(cursor, start));
    node.append(el("mark", {}, text.slice(start, end)));
    cursor = end;
  }
  if (cursor < text.length) node.append(text.slice(cursor));
  return node;
}

function lineCard(item) {
  const primary = el("div", { class: "line-text" });
  primary.append(marked(item.text, item.spans.filter(([s, e]) => e <= item.text.length)));
  const card = el("div", { class: "line-card", onclick: () => item.shot_id && openShot(item.shot_id) },
    el("img", { src: item.shot_thumb ? `/media/thumbs/${item.shot_thumb}` : "", loading: "lazy", alt: "" }),
    el("div", {},
      primary,
      item.text_zh ? el("div", { class: "line-zh" }, item.text_zh) : null,
      el("div", { class: "line-ctx" },
        item.prev ? el("div", {}, el("b", {}, "上一句  "), item.prev) : null,
        item.next ? el("div", {}, el("b", {}, "下一句  "), item.next) : null),
      el("div", { class: "line-meta" },
        `${item.title} · ${item.timestamp}${item.shot_id ? " · 点击看画面" : ""}`,
        el("button", {
          class: "play-line",
          onclick: (event) => {
            event.stopPropagation();
            openPlayerAt(item.title_slug, item.start_ms, `${item.title} · ${item.timestamp}`);
          },
        }, "▶ 从这句开始播")))
  );
  return card;
}

/* ---------------- decks ---------------- */

async function loadDecks() {
  const data = await api("/api/decks");
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" }, el("h2", {}, "参考板"), el("span", { class: "count" }, `${data.items.length} 个`)),
    el("form", { class: "agent-form", style: "max-width:520px;margin-bottom:18px", onsubmit: async (event) => {
      event.preventDefault();
      const name = event.target.name.value.trim() || "参考板";
      await api("/api/decks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) });
      toast("已创建");
      loadDecks();
    } },
      el("input", { class: "agent-input", name: "name", placeholder: "新参考板名字，例如：冷调夜景参考" }),
      el("button", { class: "agent-send", type: "submit" }, "新建"))
  );
  if (!data.items.length) {
    view.append(el("div", { class: "empty" }, "还没有参考板。新建一个，然后在镜头卡片上点「加入板」。"));
    return;
  }
  const list = el("div", { class: "deck-list" });
  for (const deck of data.items) {
    list.append(el("div", { class: "deck-row" },
      el("div", {}, el("b", {}, deck.name), el("span", { class: "hint" }, ` · ${deck.count} 项`)),
      el("div", { style: "display:flex;gap:8px" },
        el("button", { onclick: () => openDeck(deck.id) }, "打开"),
        el("button", { onclick: () => window.open(`/api/decks/${deck.id}/collage`, "_blank") }, "导出拼图"),
        el("button", { onclick: () => window.open(`/decks/${deck.id}/print`, "_blank") }, "打印 PDF"),
        el("button", { onclick: async () => { await api(`/api/decks/${deck.id}`, { method: "DELETE" }); loadDecks(); } }, "删除"))));
  }
  view.append(list);
}

async function openDeck(id) {
  const deck = await api(`/api/decks/${id}`);
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" }, el("h2", {}, deck.name), el("span", { class: "count" }, `${deck.items.length} 项`)),
    el("div", { class: "deck-strip" }, ...deck.items.map((item) => {
      if (item.kind === "shot" && item.shot) {
        return el("figure", { onclick: () => openShot(item.shot.id), style: "cursor:pointer" },
          el("img", { src: `/media/thumbs/${item.shot.thumb}`, alt: "" }),
          el("figcaption", {}, `${item.shot.title} · ${fmt(item.shot.start_ms)}`));
      }
      return el("div", { class: "deck-row" }, el("span", {}, item.line?.text || ""));
    })),
    el("div", { class: "rail-actions", style: "max-width:420px" },
      el("button", { onclick: () => window.open(`/api/decks/${id}/collage`, "_blank") }, "导出拼图"),
      el("button", { onclick: () => window.open(`/decks/${id}/print`, "_blank") }, "打印 / 另存为 PDF"),
      el("button", { onclick: loadDecks }, "返回列表"))
  );
}

async function addToDeck(kind, refId) {
  if (!state.decks.length) {
    const deck = await api("/api/decks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "面试演示板" }) });
    state.decks = (await api("/api/decks")).items;
    await api(`/api/decks/${deck.id}/items`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind, ref_id: refId }) });
    toast("已新建「面试演示板」并加入");
    return;
  }
  const deck = state.decks[0];
  await api(`/api/decks/${deck.id}/items`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind, ref_id: refId }) });
  toast(`已加入「${deck.name}」`);
}

/* ---------------- agent ---------------- */

async function askAgent(message) {
  const button = $("#agent-send");
  button.disabled = true;
  try {
    const reply = await api("/api/agent", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message }),
    });
    state.agent = reply;
    state.agentActive = true;
    state.filters = {};
    for (const key of DIMENSIONS) if (reply.path.includes(`/${key}/`)) {
      const value = reply.path.split(`/${key}/`)[1]?.split("/")[0];
      if (value) state.filters[key] = decodeURIComponent(value);
    }
    renderAgentReply(reply);
    if (state.view !== "agent") setView("agent");
    else render();
    syncUrl();
  } finally {
    button.disabled = false;
  }
}

function renderAgentReply(reply) {
  const box = $("#agent-reply");
  box.hidden = false;
  box.replaceChildren(
    el("div", { class: "agent-answer" }, reply.answer),
    el("div", { class: "trace" }, ...reply.trace.map((step) =>
      el("span", { class: "trace-step" },
        el("b", {}, step.tool), " ", JSON.stringify(step.args), " → ",
        el("b", {}, step.count), ` 条 / ${step.ms}ms`))),
    el("div", { class: "chips" }, ...reply.followups.map((text) =>
      el("button", { class: "chip", onclick: () => { $("#agent-input").value = text; askAgent(text); } }, text)))
  );
}

/* ---------------- render ---------------- */

function renderAgentResults() {
  const reply = state.agent;
  const view = $("#view");
  view.replaceChildren();
  if (reply.lines.length) {
    view.append(el("div", { class: "result-head" },
      el("h2", {}, "台词命中"), el("span", { class: "count" }, `${reply.lines.length} 条`),
      el("span", { class: "path" }, "每条都带前后句和对应画面")));
    const list = el("div", { class: "lines" });
    for (const item of reply.lines) list.append(lineCard(item));
    view.append(list);
  }
  if (reply.shots.length) {
    view.append(el("div", { class: "result-head", style: "margin-top:22px" },
      el("h2", {}, "画面命中"), el("span", { class: "count" }, `${reply.trace.find(t => t.tool === "search_shots")?.count ?? reply.shots.length} 个镜头`),
      el("span", { class: "path" }, reply.path)));
    const grid = el("div", { class: "grid" });
    for (const shot of reply.shots) grid.append(shotCard(shot));
    view.append(grid);
  }
  if (!reply.lines.length && !reply.shots.length) {
    view.append(el("div", { class: "empty" }, "没有命中。换个说法，或直接在左侧点筛选项。"));
  }
}

async function renderLibraryPreview() {
  const data = await api("/api/shots?limit=12");
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" },
      el("h2", {}, "库里现在有这些镜头"),
      el("span", { class: "count" }, `${data.total} 个 · 全部由 ffmpeg 抽帧并算出调色板`),
      el("span", { class: "path" }, "问一句，或直接点左侧筛选")),
    el("div", { class: "grid" }, ...data.items.map(shotCard))
  );
}

async function render() {
  syncUrl();
  if (state.view === "agent") {
    await loadFacets();
    if (state.agent) renderAgentResults();
    else await renderLibraryPreview();
  } else if (state.view === "shots") {
    await loadFacets();
    await loadShots();
  } else if (state.view === "lines") {
    await loadFacets();
    await loadLines(state.lastKeyword || "");
  } else if (state.view === "decks") {
    state.decks = (await api("/api/decks")).items;
    await loadDecks();
  }
}

function setView(view) {
  state.view = view;
  for (const button of document.querySelectorAll("#nav button")) {
    button.setAttribute("aria-selected", String(button.dataset.view === view));
  }
  $("#agent-panel").hidden = view !== "agent" && view !== "shots";
  render();
}

/* ---------------- boot ---------------- */

async function boot() {
  const meta = await api("/api/health");
  $("#stat").textContent = `${meta.titles} 部 · ${meta.shots} 个镜头 · ${meta.lines} 条台词`;

  for (const suggestion of [
    "找冷色调、暗一点的镜头",
    "暖调长镜头",
    "钢铁之泪里说 robot 的台词",
    "高对比、低饱和的画面",
  ]) {
    $("#chips").append(el("button", { class: "chip", onclick: () => { $("#agent-input").value = suggestion; askAgent(suggestion); } }, suggestion));
  }

  $("#agent-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("#agent-input").value.trim();
    if (value) askAgent(value);
  });
  for (const button of document.querySelectorAll("#nav button")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
  $("#modal-close").addEventListener("click", () => $("#modal").classList.remove("open"));
  $("#modal").addEventListener("click", (event) => { if (event.target.id === "modal") $("#modal").classList.remove("open"); });
  $("#reset").addEventListener("click", () => {
    state.filters = {}; state.shade = null; state.offset = 0; state.agentActive = false;
    $("#agent-reply").hidden = true;
    render();
  });
  $("#copy-link").addEventListener("click", async () => {
    await navigator.clipboard.writeText(location.origin + pathString());
    toast("查询链接已复制，打开即可复现同一组结果");
  });
  for (const key of ["distance", "proportion"]) {
    $(`#${key}`).addEventListener("input", (event) => {
      state[key] = Number(event.target.value);
      $(`#${key}-v`).textContent = key === "proportion" ? `${state[key]}%` : state[key];
    });
  }
  $("#shade").addEventListener("input", (event) => { state.shade = event.target.value; });
  $("#apply-shade").addEventListener("click", () => {
    state.shade = $("#shade").value;
    setView("shots");
  });

  const path = location.pathname;
  if (path.startsWith("/browse") && path.length > 8) {
    const segments = path.replace("/browse/", "").split("/").filter(Boolean);
    for (let i = 0; i + 1 < segments.length; i += 2) {
      const [key, value] = [segments[i], decodeURIComponent(segments[i + 1])];
      if (DIMENSIONS.includes(key)) state.filters[key] = value;
      else if (key === "shade") {
        const [hex, distance, proportion] = value.split("~");
        state.shade = `#${hex}`;
        state.distance = Number(distance) || 8;
        state.proportion = Number(proportion) || 3;
      } else if (key === "sort") state.sort = value;
    }
    setView("shots");
    return;
  }
  state.decks = (await api("/api/decks")).items;
  setView("agent");
}

boot().catch((error) => {
  $("#view").textContent = `启动失败：${error.message}`;
});

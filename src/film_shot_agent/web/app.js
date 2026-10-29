/* Shot Agent — Genie daylight-studio front end.
   Rules taken from the style reference: weight 500 only, tight tracking,
   32px cards / pill tags, no card shadows, one dark fill. */

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
  lastKeyword: "",
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
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};

const fmt = (ms) => {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  return `${m}:${String(total % 60).padStart(2, "0")}`;
};

let toastTimer;
function toast(text) {
  const node = $("#toast");
  node.textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2400);
}

/* ---------------- query state ---------------- */

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
  for (const key of DIMENSIONS) {
    if (state.filters[key]) parts.push(key, encodeURIComponent(state.filters[key]));
  }
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
    const group = el("div", { class: "facet-group" });
    group.append(
      el("div", { class: "label" },
        el("span", {}, DIM_LABELS[key] || key),
        el("span", { class: "tabular" }, state.filters[key] ? "已选" : ""))
    );
    const row = el("div", { class: "facet" });
    for (const item of values.slice(0, 10)) {
      row.append(
        el("button", {
          "aria-pressed": String(item.selected),
          onclick: () => toggle(key, item.value),
        }, el("span", {}, item.label), el("span", { class: "num" }, item.count))
      );
    }
    group.append(row);
    rail.append(group);
  }
  if (!rail.children.length) rail.append(el("p", { class: "hint" }, "库还没建索引。"));
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
  view.replaceChildren(
    el("div", { class: "result-head" },
      el("h2", {}, "镜头"),
      el("span", { class: "count" }, `${data.total} 个`),
      el("span", { class: "path" }, data.path),
      el("select", {
        class: "select",
        onchange: (event) => { state.sort = event.target.value; state.offset = 0; render(); },
      }, ...Object.entries({
        relevance: "默认", time: "时间顺序", bright: "由亮到暗",
        dark: "由暗到亮", long: "长镜头优先",
      }).map(([value, label]) => el("option", { value, selected: state.sort === value }, label))))
  );
  if (!data.items.length) {
    view.append(el("div", { class: "empty" }, "这个组合没有镜头。放宽条件，或清空筛选。"));
    return;
  }
  view.append(el("div", { class: "grid" }, ...data.items.map(shotCard)));
  if (data.total > data.items.length) {
    view.append(el("div", { class: "more" },
      el("button", {
        class: "btn", onclick: () => { state.offset += state.limit; loadShots(); },
      }, `再看 ${Math.min(state.limit, data.total - data.items.length)} 个`)));
  }
}

function paletteBar(swatches) {
  return el("div", { class: "palette" }, ...swatches.slice(0, 8).map((swatch) =>
    el("i", {
      style: `background:#${swatch.hex.replace("#", "")}`,
      title: `${swatch.hex} ${(swatch.weight * 100).toFixed(0)}%`,
    })));
}

function shotCard(shot) {
  return el("article", { class: "shot" },
    el("div", { class: "shot-img", onclick: () => openShot(shot.id) },
      el("img", { src: `/media/thumbs/${shot.thumb}`, loading: "lazy", alt: "" }),
      el("span", { class: "shot-badge" }, fmt(shot.start_ms))),
    paletteBar(shot.look.palette),
    el("div", { class: "shot-body" },
      el("div", { class: "shot-title" }, el("b", {}, shot.title), el("span", {}, shot.year || "")),
      el("div", { class: "shot-meta" },
        `${shot.look.color_temp_label} · ${shot.aspect_ratio}:1 · ${shot.resolution}`),
      el("div", { class: "shot-actions" },
        el("button", { onclick: () => openShot(shot.id) }, "播放"),
        el("button", { onclick: () => exportClip(shot.id, "gif-s") }, "GIF"),
        el("button", { onclick: () => addToDeck("shot", shot.id) }, "加入板"))));
}

/* ---------------- player ---------------- */

function playerBlock(slug, startMs, label) {
  const wrap = el("div", { class: "player" },
    el("video", {
      id: "player", controls: "controls", preload: "metadata",
      playsinline: "playsinline", src: `/media/video/${slug}`,
    }),
    el("div", { class: "player-bar" },
      el("span", { class: "player-label" }, label),
      el("span", { class: "hint" }, "J / K / L 逐帧 · 空格播放暂停")));
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
    if (event.target.matches("input, textarea, select")) return;
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
  $("#modal-close").addEventListener("click", () => document.removeEventListener("keydown", onKey), { once: true });
}

async function openPlayerAt(slug, startMs, label) {
  $("#modal-body").replaceChildren(playerBlock(slug, startMs, label));
  $("#modal").classList.add("open");
  bindPlayerKeys();
}

async function openShot(id) {
  const shot = await api(`/api/shots/${id}`);
  $("#modal-body").replaceChildren(
    playerBlock(shot.title_slug, shot.start_ms, `${shot.title} · ${fmt(shot.start_ms)}`),
    el("div", { class: "modal-body" },
      el("div", {},
        paletteBar(shot.look.palette),
        el("dl", { class: "kv" },
          el("dt", {}, "影片"), el("dd", {}, `${shot.title} (${shot.year})`),
          el("dt", {}, "时间点"), el("dd", {}, `${fmt(shot.start_ms)} – ${fmt(shot.end_ms)}`),
          el("dt", {}, "画幅"), el("dd", {}, `${shot.aspect_ratio}:1 · ${shot.resolution}`),
          el("dt", {}, "亮度"), el("dd", {}, shot.look.brightness.toFixed(2)),
          el("dt", {}, "对比度"), el("dd", {}, shot.look.contrast.toFixed(2)),
          el("dt", {}, "饱和度"), el("dd", {}, shot.look.saturation.toFixed(2)),
          el("dt", {}, "色调"), el("dd", {}, shot.look.color_temp_label),
          el("dt", {}, "调色板"), el("dd", {},
            shot.look.palette.map((s) => `#${s.hex.replace("#", "")} ${(s.weight * 100).toFixed(0)}%`).join("  "))),
        el("p", { class: "hint", style: "margin-top:20px" }, shot.title_attribution || "")),
      el("div", {},
        el("h3", { style: "font:500 14px/1.4 var(--font-ui); color:var(--color-fog)" }, "导出这一段"),
        el("div", { class: "export" },
          el("button", { onclick: () => exportClip(shot.id, "mp4") }, "MP4"),
          ...["xs", "s", "m", "l", "xl"].map((size) =>
            el("button", { onclick: () => exportClip(shot.id, `gif-${size}`) }, `GIF ${size.toUpperCase()}`)),
          el("button", { onclick: () => addToDeck("shot", shot.id) }, "加入参考板")),
        el("p", { class: "hint", style: "margin-top:20px" },
          "镜头切自影片原始文件，导出与播放都在本地完成。")))
  );
  $("#modal").classList.add("open");
  bindPlayerKeys();
}

async function exportClip(id, format) {
  toast(`正在用 ffmpeg 导出 ${format.toUpperCase()}…`);
  const link = document.createElement("a");
  link.href = `/api/shots/${id}/clip?fmt=${format}`;
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
      el("h2", {}, "台词"),
      el("span", { class: "count" }, keyword ? `${data.total} 条` : "输入关键词"),
      el("span", { class: "path" }, keyword ? `「${keyword}」` : "—")),
    el("form", {
      class: "inline-form",
      onsubmit: (event) => { event.preventDefault(); loadLines(event.target.q.value.trim()); },
    }, el("input", { name: "q", value: keyword || "", placeholder: "搜台词原文或中文翻译，例如 robot、机器人" }),
      el("button", { class: "btn", type: "submit" }, "搜台词"))
  );
  if (!keyword) return;
  if (!data.items.length) {
    view.append(el("div", { class: "empty" }, "没有匹配的台词。试试更短的词。"));
    return;
  }
  view.append(el("div", { class: "lines" }, ...data.items.map(lineCard)));
}

function marked(text, spans) {
  if (!spans || !spans.length) return document.createTextNode(text);
  const node = document.createElement("span");
  let cursor = 0;
  for (const [start, end] of spans) {
    if (start < cursor) continue;
    if (start > cursor) node.append(text.slice(cursor, start));
    node.append(el("mark", {}, text.slice(start, end)));
    cursor = end;
  }
  if (cursor < text.length) node.append(text.slice(cursor));
  return node;
}

function lineCard(item) {
  const primary = el("div", { class: "line-text" });
  primary.append(marked(item.text, (item.spans || []).filter(([s, e]) => e <= item.text.length)));
  return el("article", { class: "line-card", onclick: () => item.shot_id && openShot(item.shot_id) },
    el("img", { src: item.shot_thumb ? `/media/thumbs/${item.shot_thumb}` : "", loading: "lazy", alt: "" }),
    el("div", {},
      primary,
      item.text_zh ? el("div", { class: "line-zh" }, item.text_zh) : null,
      el("div", { class: "line-ctx" },
        item.prev ? el("div", {}, el("b", {}, "上一句　"), item.prev) : null,
        item.next ? el("div", {}, el("b", {}, "下一句　"), item.next) : null),
      el("div", { class: "line-foot" },
        el("span", { class: "line-meta" }, `${item.title} · ${item.timestamp}`),
        el("button", {
          class: "play-line",
          onclick: (event) => {
            event.stopPropagation();
            openPlayerAt(item.title_slug, item.start_ms, `${item.title} · ${item.timestamp}`);
          },
        }, "▶ 从这句开始播"))));
}

/* ---------------- decks ---------------- */

async function loadDecks() {
  const data = await api("/api/decks");
  state.decks = data.items;
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" },
      el("h2", {}, "参考板"),
      el("span", { class: "count" }, `${data.items.length} 个`)),
    el("form", {
      class: "inline-form",
      onsubmit: async (event) => {
        event.preventDefault();
        const name = event.target.name.value.trim() || "参考板";
        await api("/api/decks", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ name }),
        });
        toast("已创建");
        loadDecks();
      },
    }, el("input", { name: "name", placeholder: "新参考板名字，例如：冷调夜景参考" }),
      el("button", { class: "btn", type: "submit" }, "新建")));

  if (!data.items.length) {
    view.append(el("div", { class: "empty" },
      "还没有参考板。新建一个，然后在镜头卡片上点「加入板」。"));
    return;
  }
  view.append(el("div", { class: "deck-list" }, ...data.items.map((deck) =>
    el("div", { class: "deck-row" },
      el("div", {},
        el("div", { class: "name", title: deck.name }, deck.name),
        el("div", { class: "meta" }, `${deck.count} 项`)),
      el("div", { class: "deck-actions" },
        el("button", { onclick: () => openDeck(deck.id) }, "打开"),
        el("button", { onclick: () => window.open(`/api/decks/${deck.id}/collage`, "_blank") }, "导出拼图"),
        el("button", { onclick: () => window.open(`/decks/${deck.id}/print`, "_blank") }, "打印 PDF"),
        el("button", {
          onclick: async () => {
            await api(`/api/decks/${deck.id}`, { method: "DELETE" });
            loadDecks();
          },
        }, "删除"))))));
}

async function openDeck(id) {
  const deck = await api(`/api/decks/${id}`);
  const view = $("#view");
  view.replaceChildren(
    el("div", { class: "result-head" },
      el("h2", {}, deck.name),
      el("span", { class: "count" }, `${deck.items.length} 项`)),
    el("div", { class: "deck-strip" }, ...deck.items.map((item) => {
      if (item.kind === "shot" && item.shot) {
        return el("figure", { style: "cursor:pointer", onclick: () => openShot(item.shot.id) },
          el("img", { src: `/media/thumbs/${item.shot.thumb}`, alt: "" }),
          el("figcaption", {}, `${item.shot.title} · ${fmt(item.shot.start_ms)}`));
      }
      return el("div", { class: "quote" },
        el("p", {}, item.line?.text || ""),
        item.line?.text_zh ? el("p", { style: "color:var(--color-iris-blue)" }, item.line.text_zh) : null,
        el("small", {}, `${item.line?.title || ""} · ${item.line?.timestamp || ""}`));
    })),
    el("div", { style: "display:flex;gap:8px;margin-top:32px" },
      el("button", { class: "btn btn-sm", onclick: () => window.open(`/api/decks/${id}/collage`, "_blank") }, "导出拼图"),
      el("button", { class: "btn btn-sm btn-quiet", onclick: () => window.open(`/decks/${id}/print`, "_blank") }, "打印 / 另存为 PDF"),
      el("button", { class: "btn btn-sm btn-quiet", onclick: loadDecks }, "返回列表"))
  );
}

async function addToDeck(kind, refId) {
  if (!state.decks.length) {
    const deck = await api("/api/decks", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "演示参考板" }),
    });
    state.decks = (await api("/api/decks")).items;
    await api(`/api/decks/${deck.id}/items`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind, ref_id: refId }),
    });
    toast("已新建「演示参考板」并加入");
    return;
  }
  const deck = state.decks[0];
  await api(`/api/decks/${deck.id}/items`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind, ref_id: refId }),
  });
  toast(`已加入「${deck.name}」`);
}

/* ---------------- agent ---------------- */

async function askAgent(message) {
  const button = $("#agent-send");
  button.disabled = true;
  try {
    const reply = await api("/api/agent", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ message }),
    });
    state.agent = reply;
    state.filters = {};
    for (const key of DIMENSIONS) {
      const marker = `/${key}/`;
      if (!reply.path.includes(marker)) continue;
      const value = reply.path.split(marker)[1]?.split("/")[0];
      if (value) state.filters[key] = decodeURIComponent(value);
    }
    renderAnswer(reply);
    $("#hero").classList.add("compact");
    if (state.view !== "agent") setView("agent");
    else render();
    requestAnimationFrame(() => {
      $("#hero").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  } finally {
    button.disabled = false;
  }
}

function renderAnswer(reply) {
  const slot = $("#answer-slot");
  slot.replaceChildren(
    el("section", { class: "answer" },
      el("div", { class: "answer-head" },
        el("h2", {}, reply.answer),
        el("span", { class: "tag" }, reply.intent === "line" ? "台词检索" : reply.intent === "mixed" ? "台词 + 画面" : "画面检索")),
      el("div", { class: "trace" }, ...reply.trace.map((step) =>
        el("span", { class: "trace-step" },
          el("b", {}, step.tool), " ", JSON.stringify(step.args), " → ",
          el("b", {}, step.count), " 条 / ", step.ms, "ms"))),
      el("div", { class: "followups" }, ...reply.followups.map((text) =>
        el("button", { class: "chip", onclick: () => { $("#agent-input").value = text; askAgent(text); } }, text)))));
}

function renderAgentResults() {
  const reply = state.agent;
  const view = $("#view");
  view.replaceChildren();
  if (reply.lines.length) {
    view.append(el("div", { class: "result-head" },
      el("h2", {}, "台词命中"),
      el("span", { class: "count" }, `${reply.lines.length} 条`),
      el("span", { class: "path" }, "带前后句与对应画面")));
    view.append(el("div", { class: "lines" }, ...reply.lines.map(lineCard)));
  }
  if (reply.shots.length) {
    view.append(el("div", { class: "result-head", style: "margin-top:40px" },
      el("h2", {}, "画面命中"),
      el("span", { class: "count" },
        `${reply.trace.find((t) => t.tool === "search_shots")?.count ?? reply.shots.length} 个`),
      el("span", { class: "path" }, reply.path)));
    view.append(el("div", { class: "grid" }, ...reply.shots.map(shotCard)));
  }
  if (!reply.lines.length && !reply.shots.length) {
    view.append(el("div", { class: "empty" }, "没有命中。换个说法，或直接点左侧筛选。"));
  }
}

async function renderLibraryPreview() {
  const data = await api("/api/shots?limit=12");
  $("#view").replaceChildren(
    el("div", { class: "result-head big" },
      el("h2", {}, "库里现在有这些镜头"),
      el("span", { class: "count" }, `${data.total} 个 · 全部由 ffmpeg 抽帧并算出调色板`)),
    el("div", { class: "grid" }, ...data.items.map(shotCard)));
}

/* ---------------- render ---------------- */

async function render() {
  syncUrl();
  $("#hero").style.display = state.view === "agent" ? "" : "none";
  $("#hero").classList.toggle("compact", Boolean(state.agent));
  document.querySelector(".stage").classList.toggle("solo", state.view === "decks");
  await loadFacets();
  if (state.view === "agent") {
    if (state.agent) renderAgentResults();
    else await renderLibraryPreview();
  } else if (state.view === "shots") {
    await loadShots();
  } else if (state.view === "lines") {
    await loadLines(state.lastKeyword || "");
  } else if (state.view === "decks") {
    await loadDecks();
  }
}

function setView(view) {
  state.view = view;
  for (const button of document.querySelectorAll("#nav button")) {
    button.setAttribute("aria-selected", String(button.dataset.view === view));
  }
  render();
}

/* ---------------- boot ---------------- */

async function boot() {
  const meta = await api("/api/health");
  $("#stat").textContent = `${meta.titles} 部 · ${meta.shots} 个镜头 · ${meta.lines} 条台词`;
  if (meta.demo) $("#demo-banner").hidden = false;

  for (const suggestion of [
    "找冷色调、暗一点的镜头",
    "暖调长镜头",
    "钢铁之泪里说 robot 的台词",
    "高对比、低饱和的画面",
  ]) {
    $("#suggests").append(el("button", {
      class: "chip",
      onclick: () => { $("#agent-input").value = suggestion; askAgent(suggestion); },
    }, suggestion));
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
  $("#modal").addEventListener("click", (event) => {
    if (event.target.id === "modal") $("#modal").classList.remove("open");
  });
  $("#reset").addEventListener("click", () => {
    state.filters = {};
    state.shade = null;
    state.offset = 0;
    state.agent = null;
    $("#answer-slot").replaceChildren();
    $("#hero").classList.remove("compact");
    $("#agent-input").value = "";
    render();
  });
  $("#copy-link").addEventListener("click", async () => {
    await navigator.clipboard.writeText(location.origin + pathString());
    toast("查询链接已复制，打开即复现同一组结果");
  });
  const hexLabel = $("#shade-hex");
  $("#shade").addEventListener("input", (event) => {
    state.shade = event.target.value;
    hexLabel.textContent = event.target.value;
  });
  for (const key of ["distance", "proportion"]) {
    $(`#${key}`).addEventListener("input", (event) => {
      state[key] = Number(event.target.value);
      $(`#${key}-v`).textContent = key === "proportion" ? `${state[key]}%` : state[key];
    });
  }
  $("#apply-shade").addEventListener("click", () => {
    state.shade = $("#shade").value;
    setView("shots");
  });

  const path = location.pathname;
  if (path.startsWith("/browse") && path.length > 8) {
    const segments = path.replace("/browse/", "").split("/").filter(Boolean);
    for (let i = 0; i + 1 < segments.length; i += 2) {
      const key = segments[i];
      const value = decodeURIComponent(segments[i + 1]);
      if (DIMENSIONS.includes(key)) state.filters[key] = value;
      else if (key === "shade") {
        const [hex, distance, proportion] = value.split("~");
        state.shade = `#${hex}`;
        state.distance = Number(distance) || 8;
        state.proportion = Number(proportion) || 3;
        $("#shade").value = state.shade;
        hexLabel.textContent = state.shade;
      } else if (key === "sort") state.sort = value;
    }
    state.decks = (await api("/api/decks")).items;
    setView("shots");
    return;
  }
  state.decks = (await api("/api/decks")).items;
  setView("agent");
}

boot().catch((error) => {
  $("#view").textContent = `启动失败：${error.message}`;
});

/* 问片 — research surface. All model output is rendered as text nodes, never as HTML.
   Links are only rendered when the backend already vetted them against tool results. */

const SUGGESTS = [
  "最近有什么好看的科幻片？",
  "《盗梦空间》豆瓣和 IMDb 评分多少？",
  "哪部电影里男主角在雨中跳舞？",
  "“希望是美好的，也许是人间至善”出自哪部电影？",
  "《繁花》在哪看，有免费的吗？",
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
  return el("a", {
    class: cls,
    href: url,
    target: "_blank",
    rel: "noopener noreferrer",
  }, text);
}

function accessClass(label) {
  if (!label) return "";
  if (label.includes("广告")) return "ads";
  if (label.includes("免费")) return "free";
  if (label.includes("会员") || label.includes("付费")) return "paid";
  return "";
}

function confidenceLabel(value) {
  if (value === "high") return "置信度 高";
  if (value === "low") return "置信度 低";
  return "置信度 中";
}

let timer = null;
let startedAt = 0;

function setLoading(on) {
  const button = $("#ask-send");
  button.disabled = on;
  button.textContent = on ? "查询中…" : "问片";
  clearInterval(timer);
  if (on) {
    startedAt = Date.now();
    timer = setInterval(() => {
      const node = $("#ask-elapsed");
      if (node) node.textContent = `${Math.round((Date.now() - startedAt) / 1000)}s`;
    }, 1000);
  }
}

function showLoading(query) {
  const view = $("#ask-view");
  view.replaceChildren(
    el("div", { class: "ask-loading" },
      el("h3", {}, "正在查资料…"),
      el("p", {}, `「${query}」`),
      el("div", { class: "ask-loading-bar" }, el("i", {})),
      el("p", { class: "hint", style: "margin-top:16px" },
        "联网搜索 → 核对评分/渠道 → 整理来源。通常 10–30 秒。已用时 ",
        el("span", { id: "ask-elapsed" }, "0s"),
      ),
    ),
  );
}

function showError(message, query) {
  const view = $("#ask-view");
  view.replaceChildren(
    el("div", { class: "ask-error" },
      el("h3", {}, "这次没问成"),
      el("p", {}, message || "问片暂时不可用，请稍后再试。"),
      el("div", { class: "ask-followups" },
        el("button", { onclick: () => ask(query) }, "重试"),
      ),
    ),
  );
}

function answerCard(data) {
  const intent = INTENT_LABEL[data.intent] || "回答";
  const card = el("section", { class: "ask-answer-card" },
    el("div", { class: "ask-answer-head" },
      el("span", { class: "ask-tag strong" }, intent),
      el("span", { class: "ask-tag" }, "答案可核对"),
    ),
    el("p", { class: "ask-answer-text" }, data.answer || ""),
  );
  const meta = el("div", { class: "ask-engine" });
  if (data.engine) {
    meta.append(
      el("span", {}, `模型 ${data.engine.model || "—"}`),
      el("span", {}, `搜索 ${data.engine.search || "—"}`),
      el("span", {}, data.engine.tmdb ? "TMDB 已连接" : "TMDB 未配置"),
      el("span", {}, `${data.usage?.steps ?? 0} 步 · ${data.usage?.completion_tokens ?? 0} tokens`),
    );
  }
  if (meta.children.length) card.append(meta);
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

function filmCard(title) {
  const body = el("div", { class: "film-body" });

  const sub = [title.original_name, title.year, title.kind].filter(Boolean).join(" · ");
  const head = el("div", { class: "film-head" },
    el("div", {},
      el("h3", { class: "film-name" }, title.name || "未命名"),
      sub ? el("p", { class: "film-sub" }, sub) : null,
    ),
    el("span", { class: `conf ${title.confidence || "medium"}` }, confidenceLabel(title.confidence)),
  );
  body.append(head);

  if (title.ratings?.length) {
    const row = el("div", { class: "rating-row" });
    for (const item of title.ratings) row.append(ratingChip(item));
    body.append(row);
  }

  if (title.watch?.length) {
    const block = el("div", { class: "film-block" },
      el("h4", {}, "在哪看 · 免费优先"),
    );
    const list = el("div", { class: "watch-list" });
    for (const item of title.watch) {
      list.append(
        el("div", { class: "watch-row" },
          el("span", { class: `access ${accessClass(item.access)}` }, item.access || "需确认"),
          el("span", { class: "name" }, item.platform || "平台"),
          el("span", { class: "note" }, item.note || ""),
          outbound(item.url, "打开 ↗"),
        ),
      );
    }
    block.append(list);
    body.append(block);
  }

  if (title.reviews?.length) {
    const block = el("div", { class: "film-block" },
      el("h4", {}, "观众评价"),
    );
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
    ? el("img", { class: "film-poster", src: poster, alt: `${title.name} 海报`, loading: "lazy" })
    : el("div", { class: "film-no-poster" }, "NO POSTER");
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
  return el("section", { class: "ask-section ask-caveats" },
    el("h3", {}, "注意"),
    list,
  );
}

function traceSection(trace) {
  const rows = trace.map((step) => el("tr", {},
    el("td", {}, el("code", {}, step.tool || "")),
    el("td", {}, el("code", {}, JSON.stringify(step.args || {}).slice(0, 120))),
    el("td", {}, String(step.count ?? 0)),
    el("td", {}, `${step.ms ?? 0}ms`),
  ));
  const table = el("table", { class: "ask-trace-table" },
    el("thead", {}, el("tr", {},
      el("th", {}, "工具"), el("th", {}, "参数"), el("th", {}, "结果"), el("th", {}, "耗时"),
    )),
    el("tbody", {}, ...rows),
  );
  const details = el("details", { class: "ask-trace" },
    el("summary", {}, `助理调用了 ${trace.length} 次工具（点开看 trace）`),
    table,
  );
  return details;
}

function followupsSection(followups) {
  const row = el("div", { class: "ask-followups" });
  for (const text of followups) {
    row.append(el("button", { onclick: () => ask(text) }, text));
  }
  return row;
}

function renderResult(data) {
  const view = $("#ask-view");
  const result = el("div", { class: "ask-result" }, answerCard(data));
  if (data.titles?.length) result.append(titlesSection(data.titles));
  if (data.citations?.length) result.append(citationsSection(data.citations));
  if (data.caveats?.length) result.append(caveatsSection(data.caveats));
  if (data.trace?.length) result.append(traceSection(data.trace));
  if (data.followups?.length) result.append(followupsSection(data.followups));
  view.replaceChildren(result);
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function ask(question) {
  const query = String(question || "").trim();
  if (!query) return;
  $("#ask-input").value = query;
  history.replaceState(null, "", `/ask?q=${encodeURIComponent(query)}`);
  setLoading(true);
  showLoading(query);
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);
    let response;
    try {
      response = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      showError(payload?.error?.message || `问片失败（HTTP ${response.status}）。`, query);
      return;
    }
    renderResult(payload);
  } catch (error) {
    if (error?.name === "AbortError") showError("查询超时了。可以拆成更小的问题再试。", query);
    else showError("网络或服务暂时不可用，请稍后再试。", query);
  } finally {
    setLoading(false);
  }
}

function boot() {
  const suggests = $("#ask-suggests");
  for (const text of SUGGESTS) {
    suggests.append(el("button", { class: "chip", onclick: () => ask(text) }, text));
  }
  $("#ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    ask($("#ask-input").value);
  });
  fetch("/api/meta")
    .then((response) => response.json())
    .then((data) => {
      const research = data?.research || {};
      if (!research.enabled) {
        $("#engine-stat").textContent = "模型未配置";
        return;
      }
      $("#engine-stat").textContent = `联网搜索 · ${research.model || "已连接"}`;
    })
    .catch(() => {});
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) ask(initial);
}

boot();

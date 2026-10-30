import { WatchlistStore, titleKey, STORAGE_KEY } from "./watchlist-store.js";

const $ = selector => document.querySelector(selector);
let store;
let renderFilm;
let lastRemoved;

function el(tag, attrs = {}, content = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  node.textContent = content;
  return node;
}

function feedback(message, error = false) {
  const node = $("#watchlist-feedback");
  node.textContent = message;
  node.classList.toggle("error", error);
}

function syncButtons() {
  $("#watchlist-count").textContent = store.items.length;
  document.querySelectorAll(".collect-film").forEach(button => {
    const saved = store.items.some(row => titleKey(row.title) === button.dataset.key);
    button.textContent = saved ? "✓ 已在片单" : "+ 加入片单";
    button.setAttribute("aria-pressed", String(saved));
  });
}

export function collectionButton(title) {
  const button = el("button", { class: "btn btn-sm btn-quiet collect-film", type: "button" });
  button.dataset.key = titleKey(title);
  const saved = store.has(title);
  button.textContent = saved ? "✓ 已在片单" : "+ 加入片单";
  button.setAttribute("aria-pressed", String(saved));
  button.addEventListener("click", () => {
    try {
      const added = store.add(title);
      $("#watchlist-search").value = "";
      $("#watchlist-filter").value = "all";
      syncButtons();
      open();
      feedback(added ? `已收藏《${title.name}》，评分和来源已一并保留。` : "这部电影已经在片单里了。");
    } catch (error) { open(); feedback(error.message, true); }
  });
  return button;
}

function render() {
  const items = store.items;
  const watched = items.filter(row => row.status === "watched").length;
  const stats = $("#watchlist-stats");
  stats.replaceChildren(...[
    [items.length, "部已收藏"], [items.length - watched, "部想看"], [watched, "部已看"],
  ].map(([count, label]) => {
    const stat = el("div");
    stat.append(el("strong", {}, count), el("span", {}, label));
    return stat;
  }));
  const query = $("#watchlist-search").value.trim().toLocaleLowerCase();
  const status = $("#watchlist-filter").value;
  const shown = items.filter(row => (status === "all" || row.status === status) &&
    [row.title.name, row.title.original_name, row.title.year, row.note].join(" ").toLocaleLowerCase().includes(query));
  const list = $("#watchlist-items");
  list.replaceChildren();
  if (!shown.length) {
    const empty = el("div", { class: "watchlist-empty" });
    empty.append(el("h3", {}, items.length ? "没有匹配的电影" : "你的下一场电影，从这里开始。"),
      el("p", {}, items.length ? "换一个关键词或观看状态试试。" : "在问片结果中点「加入片单」，或在上方直接输入片名。"));
    list.append(empty);
  }
  for (const row of shown) {
    const key = titleKey(row.title);
    const entry = el("article", { class: "watchlist-entry" });
    const heading = el("div", { class: "watchlist-entry-head" });
    const name = el("div");
    name.append(el("h3", {}, row.title.name), el("p", {}, [row.title.year,
      `收藏于 ${new Date(row.saved_at).toLocaleDateString("zh-CN")}`].filter(Boolean).join(" · ")));
    const select = el("select", { "aria-label": `${row.title.name} 的观看状态` });
    for (const [value, label] of [["want", "想看"], ["watched", "已看"]]) select.append(el("option", { value }, label));
    select.value = row.status;
    select.addEventListener("change", () => {
      try { store.update(key, { status: select.value }); render(); feedback("观看状态已保存。"); }
      catch (error) { select.value = row.status; feedback(error.message, true); }
    });
    heading.append(name, select);
    const note = el("textarea", { rows: "2", maxlength: "1000", placeholder: "记下想看的理由，或看完后的感受…", "aria-label": `${row.title.name} 的备注` });
    note.value = row.note;
    // Save while typing, without rebuilding the editor or moving its cursor.
    note.addEventListener("input", () => {
      try { store.update(key, { note: note.value }); feedback("备注已保存。"); }
      catch (error) { feedback(error.message, true); }
    });
    const details = el("details", { class: "watchlist-details" });
    details.append(el("summary", {}, "查看收藏时的台词、评分与来源"));
    details.addEventListener("toggle", () => {
      if (details.open && details.childElementCount === 1) {
        const card = renderFilm(row.title);
        card.querySelector(".collect-film")?.remove();
        details.append(card);
      }
    });
    const remove = el("button", { class: "btn btn-sm btn-quiet watchlist-remove", type: "button" }, "移出片单");
    remove.addEventListener("click", () => {
      try {
        // Re-read to include notes edited since this entry was rendered.
        const current = store.items.find(item => titleKey(item.title) === key);
        store.remove(key);
        lastRemoved = current;
        render(); syncButtons(); feedback(`已移出《${row.title.name}》。`);
        const undo = el("button", { type: "button", class: "btn btn-sm btn-quiet" }, "撤销");
        undo.addEventListener("click", () => {
          try {
            if (lastRemoved && !store.has(lastRemoved.title)) store.commit([lastRemoved, ...store.items]);
            lastRemoved = null;
            render(); syncButtons(); feedback("已恢复到片单。");
          } catch (error) { feedback(error.message, true); }
        });
        $("#watchlist-feedback").append(undo);
      } catch (error) { feedback(error.message, true); }
    });
    entry.append(heading, note, details, remove);
    list.append(entry);
  }
  $("#export-watchlist").disabled = items.length === 0;
}

function open() {
  render();
  feedback(store.loadError, Boolean(store.loadError));
  if (!$("#watchlist").open) $("#watchlist").showModal();
}

export function initWatchlist({ filmCard }) {
  let storage;
  try { storage = window.localStorage; } catch { storage = { getItem() { throw new Error(); } }; }
  store = new WatchlistStore(storage);
  renderFilm = filmCard;
  syncButtons();
  $("#open-watchlist").addEventListener("click", open);
  $("#close-watchlist").addEventListener("click", () => $("#watchlist").close());
  $("#watchlist-search").addEventListener("input", render);
  $("#watchlist-filter").addEventListener("change", render);
  $("#watchlist-add").addEventListener("submit", event => {
    event.preventDefault();
    try {
      const added = store.add({ name: $("#watchlist-name").value, year: $("#watchlist-year").value });
      if (added) {
        event.target.reset();
        $("#watchlist-search").value = "";
        $("#watchlist-filter").value = "all";
      }
      render(); syncButtons(); feedback(added ? "已加入片单。" : "同名同年份的电影已在片单中。");
    } catch (error) { feedback(error.message, true); }
  });
  $("#export-watchlist").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([store.export()], { type: "application/json" }));
    const link = el("a", { href: url, download: `我的片单-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    feedback("备份已导出，包含片单、备注与来源。请妥善保存。");
  });
  $("#import-watchlist").addEventListener("click", () => $("#watchlist-file").click());
  $("#watchlist-file").addEventListener("change", async event => {
    const file = event.target.files[0];
    try {
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) throw new Error("备份过大，请选择小于 5 MB 的片单文件。");
      const added = store.merge(await file.text());
      render(); syncButtons(); feedback(`已导入 ${added} 部新电影；已有条目的状态和备注保持不变。`);
    } catch (error) { feedback(error.message, true); }
    finally { event.target.value = ""; }
  });
  window.addEventListener("storage", event => {
    if (event.key !== null && event.key !== STORAGE_KEY) return;
    store = new WatchlistStore(storage);
    syncButtons();
    if ($("#watchlist").open) { render(); feedback(store.loadError || "片单已与其他标签页同步。", Boolean(store.loadError)); }
  });
}

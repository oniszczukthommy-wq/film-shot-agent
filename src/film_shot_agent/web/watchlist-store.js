/* Browser-local collection. Writes succeed before in-memory state changes. */
export const STORAGE_KEY = "film-shot-agent-watchlist-v1";
export const LIMIT = 500;
const text = (value, max = 200) => typeof value === "string" ? value.trim().slice(0, max) : "";
const fields = (value, keys) => Object.fromEntries(keys.map(key => [key, text(value?.[key], 2000)]));
const rows = (value, keys) => Array.isArray(value) ? value.slice(0, 20)
  .filter(row => row && typeof row === "object").map(row => fields(row, keys)) : [];

export function normalizeTitle(value) {
  if (!value || typeof value !== "object" || !text(value.name)) throw new Error("片名不能为空。");
  const title = fields(value, ["name", "original_name", "kind", "confidence", "poster", "poster_fallback"]);
  title.name = text(value.name);
  const year = String(value.year || "");
  title.year = /^\d{4}$/.test(year) ? year : "";
  title.ratings = rows(value.ratings, ["source", "score", "out_of", "note", "url"]);
  // API ratings may be numeric; preserve them as display text.
  title.ratings.forEach((rating, i) => {
    for (const key of ["score", "out_of"]) {
      const original = value.ratings.filter(row => row && typeof row === "object")[i][key];
      if (typeof original === "number" && Number.isFinite(original)) rating[key] = String(original);
    }
  });
  title.watch = rows(value.watch, ["platform", "access", "note", "url"]);
  title.watch.forEach((row, i) => {
    row.direct = value.watch.filter(item => item && typeof item === "object")[i].direct === true;
  });
  title.reviews = rows(value.reviews, ["source", "summary", "url"]);
  title.evidence = Array.isArray(value.evidence) ? value.evidence.slice(0, 20).map(row => text(row, 2000)).filter(Boolean) : [];
  title.scene = fields(value.scene, ["quote", "line", "line_zh", "character", "timecode",
    "clip_platform", "source_url", "source_label", "confidence", "description", "clip_url"]);
  const subtitleId = Number(value.scene?.subtitle_id);
  if (Number.isSafeInteger(subtitleId) && subtitleId > 0) title.scene.subtitle_id = subtitleId;
  return title;
}

export function titleKey(title) {
  return `${text(title.name).normalize("NFKC").replace(/\s+/g, " ").toLocaleLowerCase()}|${title.year || ""}`;
}

function normalizeEntry(row) {
  if (!row || !["want", "watched"].includes(row.status)) throw new Error("备份中的观看状态无效。");
  return {
    title: normalizeTitle(row.title), status: row.status, note: text(row.note, 1000),
    saved_at: typeof row.saved_at === "string" && Number.isFinite(Date.parse(row.saved_at))
      ? new Date(row.saved_at).toISOString() : new Date().toISOString(),
  };
}

export function parseBackup(raw) {
  let data;
  try { data = JSON.parse(raw); } catch { throw new Error("无法读取 JSON 备份，请选择片单导出的文件。"); }
  if (data?.version !== 1 || !Array.isArray(data.items)) throw new Error("这不是支持的片单备份（版本 1）。");
  if (data.items.length > LIMIT) throw new Error(`片单最多保存 ${LIMIT} 部电影。`);
  const unique = new Map();
  for (const row of data.items) {
    const entry = normalizeEntry(row);
    if (!unique.has(titleKey(entry.title))) unique.set(titleKey(entry.title), entry);
  }
  return [...unique.values()];
}

export class WatchlistStore {
  constructor(storage) {
    this.storage = storage;
    this.items = [];
    this.loadError = "";
    try {
      const raw = storage.getItem(STORAGE_KEY);
      if (raw) this.items = parseBackup(raw);
    } catch {
      this.loadError = "无法读取本地片单。请检查浏览器存储设置后刷新；原有数据未被覆盖。";
    }
  }
  has(title) { return this.items.some(row => titleKey(row.title) === titleKey(title)); }
  commit(items) {
    if (this.loadError) throw new Error(this.loadError);
    if (items.length > LIMIT) throw new Error(`片单最多保存 ${LIMIT} 部电影，请先移除部分条目。`);
    try { this.storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, items })); }
    catch { throw new Error("片单未保存：浏览器存储不可用或空间不足。请导出备份后重试。"); }
    this.items = items;
  }
  add(value) {
    const title = normalizeTitle(value);
    if (this.has(title)) return false;
    this.commit([{ title, status: "want", note: "", saved_at: new Date().toISOString() }, ...this.items]);
    return true;
  }
  update(key, changes) {
    this.commit(this.items.map(row => titleKey(row.title) === key ? normalizeEntry({ ...row, ...changes }) : row));
  }
  remove(key) { this.commit(this.items.filter(row => titleKey(row.title) !== key)); }
  merge(raw) {
    const incoming = parseBackup(raw);
    const existing = new Set(this.items.map(row => titleKey(row.title)));
    const added = incoming.filter(row => !existing.has(titleKey(row.title)));
    // Keep current status and notes when importing an older copy of the same film.
    this.commit([...added, ...this.items]);
    return added.length;
  }
  export() { return JSON.stringify({ version: 1, items: this.items }, null, 2); }
}

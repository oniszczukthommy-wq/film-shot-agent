// Run with Node.js: node tests/test_watchlist.mjs (no npm dependencies).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// The app serves ES modules without a package.json or build step.
const source = await readFile(new URL("../src/film_shot_agent/web/watchlist-store.js", import.meta.url), "utf8");
const { WatchlistStore, titleKey, parseBackup, LIMIT } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);
const memory = () => ({ value: null, getItem() { return this.value; }, setItem(_key, value) { this.value = value; } });
const storage = memory();
const store = new WatchlistStore(storage);
assert.equal(store.add({ name: "  测试电影  ", year: 2024, ratings: [{ source: "TMDB", score: 8.2, out_of: 10 }] }), true);
assert.equal(store.add({ name: "测试电影", year: "2024" }), false);
assert.equal(store.add({ name: "测试电影", year: 2025 }), true);
assert.equal(store.items[1].title.ratings[0].score, "8.2");
const key = titleKey({ name: "测试电影", year: 2024 });
store.update(key, { status: "watched", note: "好看 <script>alert(1)</script>" });
const restored = new WatchlistStore(storage);
assert.equal(restored.items[1].status, "watched");
assert.match(restored.items[1].note, /<script>/); // UI renders this as text, never HTML.
const older = store.export();
store.update(key, { note: "新的备注" });
assert.equal(store.merge(older), 0);
assert.equal(store.items[1].note, "新的备注");
store.remove(key);
assert.equal(store.has({ name: "测试电影", year: 2024 }), false);
assert.equal(store.merge(older), 1);
assert.equal(store.items[0].status, "watched");
assert.throws(() => store.merge('{"version":2,"items":[]}'), /版本/);
assert.throws(() => store.merge("bad json"), /JSON/);
const before = store.export();
assert.throws(() => store.merge(JSON.stringify({ version: 1, items: [
  { title: { name: "有效" }, status: "want" }, { title: {}, status: "want" },
] })), /片名/);
assert.equal(store.export(), before); // An invalid import is atomic.
assert.throws(() => parseBackup(JSON.stringify({ version: 1, items: Array(LIMIT + 1).fill({}) })), /最多/);
const failed = new WatchlistStore(memory());
failed.storage.setItem = () => { throw new Error("quota"); };
assert.throws(() => failed.add({ name: "不能保存" }), /未保存/);
assert.equal(failed.items.length, 0);
const corruptStorage = memory();
corruptStorage.value = "broken";
const corrupt = new WatchlistStore(corruptStorage);
assert.ok(corrupt.loadError);
assert.throws(() => corrupt.add({ name: "不能覆盖" }), /未被覆盖/);
assert.equal(corruptStorage.value, "broken");
const untrusted = parseBackup(JSON.stringify({ version: 1, items: [{
  title: { name: "非标准字段", watch: "bad", reviews: [null], evidence: {}, scene: null }, status: "want",
}] }));
assert.deepEqual(untrusted[0].title.watch, []);
assert.deepEqual(untrusted[0].title.reviews, []);
assert.deepEqual(untrusted[0].title.evidence, []);
console.log("Watchlist tests passed: persistence, deduplication, import, validation, quota and corruption.");

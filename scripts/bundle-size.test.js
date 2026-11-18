"use strict";
// Порог начального пакета (#364) должен уметь падать и не считать один ассет
// дважды: `script src` и `modulepreload` на один файл — обычная выдача Vite.
const test = require("node:test");
const assert = require("node:assert/strict");
const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const { initialAssets, measure, compare, baselineFrom } = require("./bundle-size.mjs");

function makeDist(files, html) {
  const dir = mkdtempSync(join(tmpdir(), "bundle-size-"));
  mkdirSync(join(dir, "assets"), { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    writeFileSync(join(dir, name), content);
  }
  writeFileSync(join(dir, "index.html"), html);
  return dir;
}

const HTML = `<!doctype html><html><head>
<script type="module" src="/assets/index.js"></script>
<link rel="modulepreload" href="/assets/index.js">
<link rel="modulepreload" href="/assets/vendor.js">
<link rel="stylesheet" href="/assets/index.css">
<link rel="icon" href="/favicon.ico">
<link rel="stylesheet" href="https://cdn.example/x.css">
</head><body></body></html>`;

test("initialAssets: script + modulepreload + stylesheet, без двойного счёта и внешних URL", () => {
  assert.deepEqual(initialAssets(HTML), [
    "/assets/index.js",
    "/assets/vendor.js",
    "/assets/index.css",
  ]);
});

test("measure: сумма raw и gzip по начальным ассетам", () => {
  const dir = makeDist(
    {
      "assets/index.js": "a".repeat(1000),
      "assets/vendor.js": "b".repeat(2000),
      "assets/index.css": "c".repeat(500),
      "assets/lazy.js": "d".repeat(9999),
    },
    HTML,
  );
  try {
    const measured = measure(dir);
    assert.equal(measured.assets.length, 3);
    assert.equal(measured.raw_bytes, 3500);
    // Ленивый чанк не входит в начальный пакет — иначе порог считал бы весь dist.
    assert.ok(!measured.assets.some((asset) => asset.path.includes("lazy")));
    assert.ok(measured.gzip_bytes > 0 && measured.gzip_bytes < measured.raw_bytes);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("measure: битый index.html и пропавший ассет — красный шаг, а не молчаливый ноль", () => {
  const dir = makeDist({}, "<html><head></head></html>");
  try {
    assert.throws(() => measure(dir), /не нашлось ни одного начального ассета/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }

  const broken = makeDist({}, '<script src="/assets/gone.js"></script>');
  try {
    assert.throws(() => measure(broken), /ссылается на .*gone\.js/);
  } finally {
    rmSync(broken, { recursive: true, force: true });
  }
});

test("compare: рост сверх допуска — красный, уменьшение — зелёный", () => {
  const baseline = { ...baselineFrom({ assets: 3, raw_bytes: 10000, gzip_bytes: 4000 }, "2026-11-18") };

  assert.equal(compare({ raw_bytes: 10050, gzip_bytes: 4000 }, baseline).ok, true);
  const grown = compare({ raw_bytes: 20000, gzip_bytes: 4000 }, baseline);
  assert.equal(grown.ok, false);
  assert.match(grown.detail, /начальный пакет вырос/);
  assert.match(grown.detail, /raw/);

  const gz = compare({ raw_bytes: 10000, gzip_bytes: 9000 }, baseline);
  assert.equal(gz.ok, false);
  assert.match(gz.detail, /gzip/);

  assert.equal(compare({ raw_bytes: 8000, gzip_bytes: 3000 }, baseline).ok, true);
});

test("compare: допуск 1% не прячет рост больше процента", () => {
  const baseline = { ...baselineFrom({ assets: 1, raw_bytes: 10000, gzip_bytes: 1000 }, "2026-11-18") };
  assert.equal(compare({ raw_bytes: 10100, gzip_bytes: 1000 }, baseline).ok, true);
  assert.equal(compare({ raw_bytes: 10101, gzip_bytes: 1000 }, baseline).ok, false);
});

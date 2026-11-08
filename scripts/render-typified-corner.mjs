#!/usr/bin/env node
/**
 * Типовое изображение стандартного равнополочного уголка (серия У / ЮП-уголки).
 *
 * Один шаблон на все размеры: меняется только значение линейного размера
 * (10, 15, 20, 25, 30). Картинка нужна там, где в каталоге стоит чужое фото
 * семейной ячейки: золото вместо серебра, общая карточка 1515/2525/4040 и т.п.
 *
 * Запуск:
 *   node scripts/render-typified-corner.mjs            # превью в data/tmp/typified-corners
 *   node scripts/render-typified-corner.mjs --apply    # заменить фото в data/storage-prod
 *
 * --apply сначала складывает текущие файлы в
 * data/storage-prod/backups/typified-corners-<stamp>/, потом пишет новые.
 * Пути и имена файлов берутся ровно те, что лежат в БД (photo_full/photo_thumb).
 */

import { createRequire } from "node:module";
import { copyFile, mkdir, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const requireFromFrontend = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = requireFromFrontend("playwright");

const STORAGE = join(ROOT, "data", "storage-prod");
const PRODUCTS = join(STORAGE, "products");
const PREVIEW = join(ROOT, "data", "tmp", "typified-corners");

/** размер, мм → артикулы одного и того же товара (алиасы в БД) */
const SIZES = new Map([
  [10, ["У1010", "ЮП-1401"]],
  [15, ["У1515", "ЮП-009"]],
  [20, ["У2020", "ЮП-011"]],
  [25, ["У2525", "ЮП-2004"]],
  [30, ["У3030", "ЮП-1629"]],
]);

const FULL_PX = 2000;
const THUMB_PX = 600;
const QUALITY = 95;

/** SVG-шаблон. Геометрия одна и та же, значение размера подставляется в текст. */
function html(size) {
  const label = String(size);
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
  body { background: #ffffff; font-family: "Segoe UI", "Inter", Arial, sans-serif; }
  svg { display: block; width: 100vw; height: 100vh; }
</style>
</head>
<body>
<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Уголок ГОСТ ${size}×${size}">
  <rect width="1000" height="1000" fill="#ffffff"/>

  <!-- контур уголка: одна линия, без заливки и теней -->
  <polygon points="330,670 730,670 730,590 410,590 410,270 330,270"
           fill="none" stroke="#2f343a" stroke-width="6"
           stroke-linejoin="miter" stroke-linecap="square"/>

  <!-- размер сбоку: тонкая линия и маленькое число -->
  <g stroke="#a3abb4" stroke-width="2" fill="none">
    <line x1="326" y1="270" x2="286" y2="270"/>
    <line x1="326" y1="670" x2="286" y2="670"/>
    <line x1="292" y1="270" x2="292" y2="670"/>
    <path d="M292,270 l-6,12 M292,270 l6,12"/>
    <path d="M292,670 l-6,-12 M292,670 l6,-12"/>

    <line x1="330" y1="674" x2="330" y2="710"/>
    <line x1="730" y1="674" x2="730" y2="710"/>
    <line x1="330" y1="702" x2="730" y2="702"/>
    <path d="M330,702 l12,-6 M330,702 l12,6"/>
    <path d="M730,702 l-12,-6 M730,702 l-12,6"/>
  </g>

  <g fill="#6f7883" font-size="32" font-weight="400">
    <text x="266" y="470" text-anchor="middle" transform="rotate(-90 266 470)">${label}</text>
    <text x="530" y="758" text-anchor="middle">${label}</text>
  </g>
</svg>
</body>
</html>`;
}

async function render(browser, size, outPath, px) {
  const page = await browser.newPage({
    viewport: { width: px, height: px },
    deviceScaleFactor: 1,
  });
  await page.setContent(html(size), { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: outPath, type: "jpeg", quality: QUALITY });
  await page.close();
}

function stamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  const apply = process.argv.includes("--apply");
  const outDir = apply ? PRODUCTS : PREVIEW;
  const backupDir = join(STORAGE, "backups", `typified-corners-${stamp()}`);
  await mkdir(outDir, { recursive: true });

  const browser = await chromium.launch();
  const written = [];
  try {
    for (const [size, skus] of SIZES) {
      for (const sku of skus) {
        for (const [kind, px] of [["full", FULL_PX], ["thumb", THUMB_PX]]) {
          const name = apply ? `${sku}_${kind}.jpg` : `${size}_${kind}.jpg`;
          const outPath = join(outDir, name);
          const keepName = `${sku}_${kind}.jpg`;
          if (apply && (await exists(join(PRODUCTS, keepName)))) {
            await mkdir(backupDir, { recursive: true });
            await copyFile(join(PRODUCTS, keepName), join(backupDir, keepName));
          }
          await render(browser, size, outPath, px);
          written.push({ size, sku, kind, outPath });
        }
      }
    }
  } finally {
    await browser.close();
  }

  console.log(apply ? "Заменены фото в storage:" : "Превью:");
  for (const row of written) console.log(`  ${row.size}×${row.size}  ${row.sku}  ${row.kind}`);
  if (apply) console.log(`Бэкап старых файлов: ${backupDir}`);
  else console.log(`Каталог превью: ${PREVIEW}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

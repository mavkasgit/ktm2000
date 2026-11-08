#!/usr/bin/env node
/**
 * Типовые изображения профилей 033 и 130: чистое сечение + размеры.
 *
 * Сделаны по тому же принципу, что и `render-typified-corner.mjs`: SVG-шаблон,
 * рендер Playwright в JPEG 2000 px (full) и 600 px (thumb), белый фон, тонкий
 * контур, серые размерные линии. Источники геометрии:
 *
 *   033 — сечение с плаката КТМ 2024 (41×5,4, самоклейка), обведено по
 *         отрендеренной ячейке; паспорт — КТМ/033 (ЮП-2379), P=97,6.
 *   130 — сечение с чертежа КТМ/130.pdf (44×4,1), паспорт P=106,3.
 *
 * Запуск:
 *   node scripts/render-typified-profile.mjs            # превью в data/tmp/typified-profiles
 *   node scripts/render-typified-profile.mjs --apply    # заменить фото в data/storage-prod
 *   node scripts/render-typified-profile.mjs --sku 130  # только один профиль
 *
 * --apply сначала складывает текущие файлы в
 * data/storage-prod/backups/typified-profiles-<stamp>/, потом пишет новые.
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
const PREVIEW = join(ROOT, "data", "tmp", "typified-profiles");

const FULL_PX = 2000;
const THUMB_PX = 600;
const QUALITY = 95;

/** Сечение 033 в миллиметрах: x 0..41, y 0..5,4 (0 — верх дуги). */
const P033 = [
  [0.0, 4.91], [0.91, 4.42], [1.82, 4.05], [2.73, 3.71], [3.64, 3.39],
  [4.56, 3.08], [5.47, 2.78], [6.38, 2.51], [7.29, 2.26], [8.2, 2.03],
  [9.11, 1.79], [10.02, 1.59], [10.93, 1.4], [11.84, 1.22], [12.76, 1.05],
  [13.67, 0.91], [14.58, 0.77], [15.49, 0.63], [16.4, 0.52], [17.31, 0.41],
  [18.22, 0.32], [19.13, 0.22], [20.04, 0.14], [20.96, 0.09], [21.87, 0.05],
  [22.78, 0.01], [23.69, 0.0], [24.6, 0.0], [25.51, 0.01], [26.42, 0.05],
  [27.33, 0.1], [28.24, 0.16], [29.16, 0.25], [30.07, 0.35], [30.98, 0.46],
  [31.89, 0.6], [32.8, 0.77], [33.71, 0.94], [34.62, 1.12], [35.53, 1.33],
  [36.44, 1.53], [37.36, 1.75], [38.27, 1.97], [39.18, 2.21], [40.09, 2.48],
  [41.0, 2.98], [40.54, 3.71], [39.63, 3.77], [38.72, 3.4], [37.81, 3.09],
  [36.9, 2.85], [35.99, 2.62], [35.08, 2.43], [34.17, 2.25], [33.26, 2.11],
  [32.34, 1.99], [31.43, 1.89], [30.52, 1.8], [29.61, 1.72], [28.7, 1.65],
  [27.79, 1.59], [26.88, 2.27], [25.97, 3.98], [25.06, 4.21], [24.14, 2.81],
  [23.23, 2.24], [22.32, 2.31], [21.41, 2.41], [20.5, 3.81], [19.59, 4.56],
  [18.68, 4.06], [17.77, 2.54], [16.86, 2.03], [15.94, 2.14], [15.03, 2.25],
  [14.12, 2.38], [13.21, 2.52], [12.3, 2.67], [11.39, 2.81], [10.48, 2.96],
  [9.57, 3.13], [8.66, 3.31], [7.74, 3.49], [6.83, 3.68], [5.92, 3.89],
  [5.01, 4.1], [4.1, 4.33], [3.19, 4.57], [2.28, 4.83], [1.37, 5.09],
  [0.46, 5.29], [0.0, 5.31],
];

/** Сечение 130 в миллиметрах: x 0..44, y 0..4,1. */
const P130 = [
  ["M", 0.5, 4.1],
  ["Q", 0.0, 4.05, 0.0, 3.6],
  ["L", 8.7, 0.15],
  ["Q", 9.15, 0.0, 9.15, 0.5],
  ["L", 9.2, 2.2],
  ["L", 19.5, 2.2],
  ["L", 19.8, 1.0],
  ["L", 24.4, 1.0],
  ["L", 24.7, 2.2],
  ["L", 32.5, 2.25],
  ["L", 32.6, 0.5],
  ["Q", 32.65, 0.0, 33.15, 0.15],
  ["L", 42.9, 3.4],
  ["Q", 43.6, 3.55, 43.6, 3.95],
  ["L", 33.4, 4.1],
  ["Q", 22.0, 4.2, 0.5, 4.1],
  ["Z"],
];

const PROFILES = {
  "130": { width: 44, height: 4.1, path: P130, files: "130", dims: [["44", "h"], ["4,1", "v"]] },
  "033": { width: 41, height: 5.4, points: P033, files: "033_205", dims: [["41", "h"], ["5,4", "v"]] },
};

function pathData(points) {
  return points.map(([x, y], index) => `${index ? "L" : "M"}${x},${y}`).join(" ") + " Z";
}

function pathFromOps(ops) {
  return ops
    .map(([op, ...args]) => `${op}${args.join(",")}`)
    .join(" ");
}

function html(profile) {
  const { width, height, dims } = profile;
  const scale = 680 / width;
  const ox = (1000 - width * scale) / 2;
  const oy = (1000 - (height * scale + 116)) / 2;
  const sx = (x) => (ox + x * scale).toFixed(2);
  const sy = (y) => (oy + y * scale).toFixed(2);

  const shape = profile.points
    ? pathData(profile.points.map(([x, y]) => [sx(x), sy(y)]))
    : pathFromOps(
        profile.path.map(([op, ...args]) =>
          op === "Z"
            ? ["Z"]
            : [op, ...args.map((value, index) => (index % 2 === 0 ? sx(value) : sy(value)))]
        )
      );

  const bottom = sy(height);
  const dimY = Number(bottom) + 70;
  const dimVX = Number(sx(width)) + 62;
  const dimVXLeft = Number(sx(0)) - 62;
  const [hLabel, vLabel] = [dims[0][0], dims[1][0]];

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
<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Сечение профиля">
  <rect width="1000" height="1000" fill="#ffffff"/>

  <path d="${shape}" fill="#ffffff" stroke="#2f343a" stroke-width="6"
        stroke-linejoin="round" stroke-linecap="round"/>

  <g stroke="#a3abb4" stroke-width="2" fill="none">
    <line x1="${sx(0)}" y1="${dimY}" x2="${sx(width)}" y2="${dimY}"/>
    <line x1="${sx(0)}" y1="${dimY - 12}" x2="${sx(0)}" y2="${dimY + 12}"/>
    <line x1="${sx(width)}" y1="${dimY - 12}" x2="${sx(width)}" y2="${dimY + 12}"/>
    <path d="M${sx(0)},${dimY} l14,-6 M${sx(0)},${dimY} l14,6"/>
    <path d="M${sx(width)},${dimY} l-14,-6 M${sx(width)},${dimY} l-14,6"/>

    <line x1="${dimVX}" y1="${sy(0)}" x2="${dimVX}" y2="${bottom}"/>
    <line x1="${dimVX - 12}" y1="${sy(0)}" x2="${dimVX + 12}" y2="${sy(0)}"/>
    <line x1="${dimVX - 12}" y1="${bottom}" x2="${dimVX + 12}" y2="${bottom}"/>
    <path d="M${dimVX},${sy(0)} l-6,14 M${dimVX},${sy(0)} l6,14"/>
    <path d="M${dimVX},${bottom} l-6,-14 M${dimVX},${bottom} l6,-14"/>
  </g>

  <g fill="#6f7883" font-size="32" font-weight="400">
    <text x="${(Number(sx(0)) + Number(sx(width))) / 2}" y="${dimY + 46}" text-anchor="middle">${hLabel}</text>
    <text x="${dimVX + 34}" y="${(Number(sy(0)) + Number(bottom)) / 2 + 10}"
          text-anchor="start">${vLabel}</text>
  </g>
</svg>
</body>
</html>`;
}

async function render(browser, profile, outPath, px) {
  const page = await browser.newPage({
    viewport: { width: px, height: px },
    deviceScaleFactor: 1,
  });
  await page.setContent(html(profile), { waitUntil: "load" });
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
  const skuArg = process.argv.indexOf("--sku");
  const only = skuArg > -1 ? process.argv[skuArg + 1] : null;
  const outDir = apply ? PRODUCTS : PREVIEW;
  const backupDir = join(STORAGE, "backups", `typified-profiles-${stamp()}`);
  await mkdir(outDir, { recursive: true });

  const browser = await chromium.launch();
  const written = [];
  try {
    for (const [sku, profile] of Object.entries(PROFILES)) {
      if (only && sku !== only) continue;
      for (const [kind, px] of [["full", FULL_PX], ["thumb", THUMB_PX]]) {
        const name = `${profile.files}_${kind}.jpg`;
        const outPath = join(outDir, name);
        if (apply && (await exists(join(PRODUCTS, name)))) {
          await mkdir(backupDir, { recursive: true });
          await copyFile(join(PRODUCTS, name), join(backupDir, name));
        }
        await render(browser, profile, outPath, px);
        written.push({ sku, kind, outPath });
      }
    }
  } finally {
    await browser.close();
  }

  console.log(apply ? "Заменены фото в storage:" : "Превью:");
  for (const row of written) console.log(`  ${row.sku}  ${row.kind}  ${row.outPath}`);
  if (apply) console.log(`Бэкап старых файлов: ${backupDir}`);
  else console.log(`Каталог превью: ${PREVIEW}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

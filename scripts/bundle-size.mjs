#!/usr/bin/env node
// Начальный пакет фронта: число, которое нельзя молча вырастить (#364).
//
// `frontend/AGENTS.md` нормирует стартовый вес числом, но до этого шага держать
// число было некому: `vite build` в CI не запускался, и статический импорт
// страницы в `Router.tsx` возвращал все разделы в начальный пакет незаметно.
//
// Что считается «начальным пакетом»: ровно то, что браузер обязан скачать до
// первого рендера, — `<script src>`, `<link rel="modulepreload">` и
// `<link rel="stylesheet">` из `dist/index.html`. Ленивые чанки разделов сюда не
// входят: они грузятся переходом в раздел, и их вес — другой разговор.
//
// Порог — закреплённое число с допуском на джиттер тулчейна (±1%): рост сверх
// него красный. Поднять порог можно только осознанно — `npm run bundle:update`
// (отдельная команда, не флаг внутри гейта: гейт ничего не правит).
//
// Запуск: node scripts/bundle-size.mjs [--dist frontend/dist] [--baseline путь]

import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DEFAULT_DIST = "frontend/dist";
const DEFAULT_BASELINE = "frontend/bundle-size-baseline.json";

/** Ассеты, которые браузер грузит до первого рендера: пути из index.html. */
export function initialAssets(html) {
  const paths = [];
  for (const match of html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)) {
    paths.push(match[1]);
  }
  for (const match of html.matchAll(/<link\b[^>]*>/g)) {
    const tag = match[0];
    const rel = /\brel="([^"]+)"/.exec(tag);
    const href = /\bhref="([^"]+)"/.exec(tag);
    if (!rel || !href) continue;
    if (!["modulepreload", "stylesheet"].includes(rel[1])) continue;
    paths.push(href[1]);
  }
  // Пакет один и тот же ассет может быть назван дважды (script + preload):
  // считаем файл один раз, иначе вес удваивается вместе с порогом.
  return [...new Set(paths)].filter((path) => !/^[a-z]+:/i.test(path));
}

const toDiskPath = (distDir, urlPath) => join(distDir, urlPath.replace(/^\/+/, ""));

/** Вес начального пакета: по ассету и суммой, в байтах и в gzip. */
export function measure(distDir) {
  const indexPath = join(distDir, "index.html");
  if (!existsSync(indexPath)) {
    throw new Error(`нет ${relative(ROOT, indexPath)} — сначала сборка: npm --prefix frontend run build`);
  }
  const assets = initialAssets(readFileSync(indexPath, "utf8")).map((urlPath) => {
    const file = toDiskPath(distDir, urlPath);
    if (!existsSync(file)) {
      throw new Error(`index.html ссылается на ${urlPath}, а файла нет — битая сборка`);
    }
    const bytes = readFileSync(file);
    return {
      path: urlPath,
      raw_bytes: statSync(file).size,
      gzip_bytes: gzipSync(bytes, { level: 9 }).length,
    };
  });
  if (!assets.length) {
    throw new Error("в index.html не нашлось ни одного начального ассета — изменился формат сборки");
  }
  return {
    assets,
    raw_bytes: assets.reduce((sum, asset) => sum + asset.raw_bytes, 0),
    gzip_bytes: assets.reduce((sum, asset) => sum + asset.gzip_bytes, 0),
  };
}

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} КБ`;

/** Сверка с порогом: рост сверх допуска — красный, уменьшение — зелёный. */
export function compare(measured, baseline) {
  const tolerance = Number(baseline.tolerance_percent ?? 0);
  const limitRaw = Math.floor((baseline.initial.raw_bytes * (100 + tolerance)) / 100);
  const limitGzip = Math.floor((baseline.initial.gzip_bytes * (100 + tolerance)) / 100);
  const grown = [];
  if (measured.raw_bytes > limitRaw) {
    grown.push(`raw ${kb(measured.raw_bytes)} > порога ${kb(limitRaw)}`);
  }
  if (measured.gzip_bytes > limitGzip) {
    grown.push(`gzip ${kb(measured.gzip_bytes)} > порога ${kb(limitGzip)}`);
  }
  return {
    ok: !grown.length,
    limitRaw,
    limitGzip,
    detail: grown.length
      ? `начальный пакет вырос: ${grown.join(", ")} (порог от ${baseline.updated}, допуск ${tolerance}%)`
      : `начальный пакет ${kb(measured.raw_bytes)} / ${kb(measured.gzip_bytes)} gzip — в пороге ${kb(limitRaw)} / ${kb(limitGzip)} gzip`,
  };
}

export function renderAssets(measured) {
  return measured.assets
    .toSorted((a, b) => b.raw_bytes - a.raw_bytes)
    .map(
      (asset) =>
        `${asset.path.padEnd(46)} ${kb(asset.raw_bytes).padStart(10)} / ${kb(asset.gzip_bytes).padStart(9)} gzip`,
    )
    .join("\n");
}

export function baselineFrom(measured, today) {
  return {
    updated: today,
    metric: "начальный пакет: script + modulepreload + stylesheet из dist/index.html",
    tolerance_percent: 1,
    initial: {
      assets: measured.assets.length,
      raw_bytes: measured.raw_bytes,
      gzip_bytes: measured.gzip_bytes,
    },
  };
}

export function measureAndCompare({ dist = DEFAULT_DIST, baselinePath = DEFAULT_BASELINE, update = false } = {}) {
  const measured = measure(join(ROOT, dist));
  const table = renderAssets(measured);

  if (update) {
    // Дата локальная: порог — решение человека в его часовом поясе.
    const today = new Date().toLocaleDateString("sv-SE");
    const baseline = baselineFrom(measured, today);
    writeFileSync(join(ROOT, baselinePath), `${JSON.stringify(baseline, null, 2)}\n`);
    return {
      ok: true,
      detail: `порог обновлён: ${baselinePath} — ${kb(measured.raw_bytes)} / ${kb(measured.gzip_bytes)} gzip`,
      table,
    };
  }

  const file = join(ROOT, baselinePath);
  if (!existsSync(file)) {
    return {
      ok: false,
      detail: `нет ${baselinePath} — порога нет, расти пакету нечему мешать: npm run bundle:update`,
      table,
    };
  }
  const baseline = JSON.parse(readFileSync(file, "utf8"));
  return { ...compare(measured, baseline), table };
}

function main() {
  const args = process.argv.slice(2);
  const opts = { update: false };
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--update") opts.update = true;
    else if (args[i] === "--dist") opts.dist = args[++i];
    else if (args[i] === "--baseline") opts.baselinePath = args[++i];
    else {
      console.error(`bundle-size: неизвестный аргумент ${args[i]} (есть --update, --dist, --baseline)`);
      return 2;
    }
  }
  let result;
  try {
    result = measureAndCompare(opts);
  } catch (error) {
    console.error(`bundle-size: ${error.message}`);
    return 1;
  }
  console.log(result.table);
  console.log(result.detail);
  return result.ok ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = main();
}

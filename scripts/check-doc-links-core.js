/**
 * Логика проверки markdown-ссылок: извлечение целей, отсев непроверяемых,
 * резолвинг относительно файла-источника.
 *
 * Вынесено отдельно от CLI, чтобы тестировалось без git и без чтения ФС —
 * как `ensure-dev-ports-core.js`. Запуск тестов: `npm run test:scripts`.
 *
 * Инвариант: ссылка в доке указывает на файл, который есть в git. Проверка по
 * `git ls-files`, а не по ФС: локальный неотслеживаемый файл прошёл бы на
 * машине автора и сломал бы ссылку в свежем клоне.
 */

"use strict";

/** Схема (`https:`, `mailto:`) или чистый якорь — не файл репозитория. */
const NON_FILE = /^(?:[a-z][a-z0-9+.-]*:|#)/i;

/**
 * Цель, которую стоит проверять: относительный путь без схемы и без якоря.
 * `docs/adr/`, `../AGENTS.md`, `./file.md` — да; `https://…`, `#якорь` — нет.
 */
function isCheckable(target) {
  return target !== "" && !NON_FILE.test(target);
}

/** Отбрасываем якорь и query: `f.md#a` → `f.md`, `f.md?x=1` → `f.md`. */
function stripFragment(target) {
  const cut = target.search(/[#?]/);
  return cut === -1 ? target : target.slice(0, cut);
}

/** Раскодируем percent-escaping: `my%20doc.md` → `my doc.md`. */
function decodeTarget(target) {
  try {
    return decodeURIComponent(target);
  } catch {
    return target;
  }
}

/**
 * Цели из inline-ссылок `[текст](цель)` и картинок `![alt](src)`.
 *
 * Цель читается до закрывающей скобки целиком: путь с пробелом — обычная
 * практика (`testdata/Упаковочный план.xlsx`), и обрезка по пробелу дала бы
 * ложную находку на существующем файле. Заголовок ссылки (`"ADR"`)
 * отбрасывается, угловые скобки `<цель>` разворачиваются.
 * Reference-style определения не разбираются — их в репозитории нет.
 */
function extractTargets(markdown) {
  const targets = [];
  const re = /!?\[[^\]]*\]\(([^)]*)\)/g;
  let match;
  while ((match = re.exec(markdown)) !== null) {
    let raw = match[1].trim();
    if (raw === "") continue;
    const withTitle = raw.match(/^(.*?)\s+"[^"]*"$/);
    if (withTitle) raw = withTitle[1];
    if (raw.startsWith("<") && raw.endsWith(">")) raw = raw.slice(1, -1);
    targets.push(raw);
  }
  return targets;
}

/**
 * Путь цели относительно корня репозитория. `fromFile` и результат —
 * со слэшами, независимо от ОС. `..` поднимает, `.` и пустые сегменты
 * отбрасываются, хвостовой слэш (каталог) сохраняется.
 */
function resolveTarget(fromFile, target) {
  const segments = fromFile.split("/").slice(0, -1);
  for (const part of target.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") segments.pop();
    else segments.push(part);
  }
  const resolved = segments.join("/");
  return target.endsWith("/") && !resolved.endsWith("/") ? `${resolved}/` : resolved;
}

/** Все каталоги на пути к каждому отслеживаемому файлу, с хвостовым слэшем. */
function collectDirectories(trackedPaths) {
  const directories = new Set();
  for (const path of trackedPaths) {
    const segments = path.split("/");
    for (let i = 1; i < segments.length; i += 1) {
      directories.add(`${segments.slice(0, i).join("/")}/`);
    }
  }
  return directories;
}

/**
 * Битые ссылки: у каждой — файл-источник, цель как написана, и путь,
 * в который она разрешилась (для сообщения об ошибке).
 *
 * `files`: `[{ path, content }]`, пути от корня репозитория.
 * `trackedPaths`: результат `git ls-files` — наличие файла в git.
 */
function findBrokenLinks(files, trackedPaths) {
  const trackedFiles = new Set(trackedPaths);
  const trackedDirs = collectDirectories(trackedPaths);
  const broken = [];

  for (const file of files) {
    for (const raw of extractTargets(file.content)) {
      if (!isCheckable(raw)) continue;
      const clean = decodeTarget(stripFragment(raw));
      if (clean === "") continue;

      const resolved = resolveTarget(file.path, clean);
      const exists = clean.endsWith("/")
        ? trackedDirs.has(resolved)
        : trackedFiles.has(resolved);

      if (!exists) {
        broken.push({ file: file.path, target: raw, resolved });
      }
    }
  }
  return broken;
}

module.exports = {
  isCheckable,
  stripFragment,
  decodeTarget,
  extractTargets,
  resolveTarget,
  collectDirectories,
  findBrokenLinks,
};
#!/usr/bin/env node
// Архив фото артикулов: восстановление в storage и обновление из storage.
//
// Фото лежат в `data/` (gitignore) и на каждой машине свои. Архив
// `assets/catalog-photos/` — единственная копия, которая живёт в git, поэтому
// после чистого клона или сноса `data/` картинки восстанавливаются отсюда.
//
// Использование:
//   node scripts/catalog-photos.mjs restore [--target <dir>]
//   node scripts/catalog-photos.mjs save [--source <dir>]
//
// `restore` кладёт файлы из архива в `data/storage-dev/products` (или в
// `--target`). `save` наоборот: складывает текущий storage в архив.
//
// Байт-в-байт одинаковые файлы не перезаписываются: версия фото в URL считается
// по `mtime_ns + size` (#404), и лишняя перезапись сбросила бы кэш всех фото.
// Реально изменённый файл копируется и получает новый mtime — версия меняется.

import { copyFile, mkdir, readdir, readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const ARCHIVE = join(ROOT, "assets", "catalog-photos");
const DEFAULT_TARGET = join(ROOT, "data", "storage-dev", "products");
const PHOTO_EXTENSIONS = new Set([".jpg", ".jpeg", ".png"]);

function usage(message) {
  if (message) console.error(message);
  console.error(
    "Использование: node scripts/catalog-photos.mjs restore [--target <dir>]\n" +
      "               node scripts/catalog-photos.mjs save [--source <dir>]",
  );
  process.exit(2);
}

function flagValue(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return null;
  const value = args[index + 1];
  if (!value || value.startsWith("--")) usage(`Флаг ${name} требует путь`);
  return resolve(value);
}

async function listPhotos(dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
  return entries
    .filter((entry) => entry.isFile() && PHOTO_EXTENSIONS.has(ext(entry.name)))
    .map((entry) => entry.name)
    .sort();
}

function ext(name) {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

async function sameContent(left, right) {
  const [a, b] = await Promise.all([stat(left), stat(right)]);
  if (a.size !== b.size) return false;
  const [bufA, bufB] = await Promise.all([readFile(left), readFile(right)]);
  return bufA.equals(bufB);
}

/** Копирует файлы из `from` в `to`, не трогая идентичные приёмники. */
async function copyChanged(from, to, names) {
  await mkdir(to, { recursive: true });
  let copied = 0;
  let unchanged = 0;
  for (const name of names) {
    const source = join(from, name);
    const destination = join(to, name);
    if (await sameContent(source, destination).catch(() => false)) {
      unchanged += 1;
      continue;
    }
    await copyFile(source, destination);
    copied += 1;
  }
  return { copied, unchanged };
}

const [command = "restore", ...rest] = process.argv.slice(2);

if (command === "restore") {
  const target = flagValue(rest, "--target") ?? DEFAULT_TARGET;
  const names = await listPhotos(ARCHIVE);
  if (names.length === 0) {
    console.error(`Архив пуст: ${ARCHIVE}`);
    process.exit(1);
  }
  const { copied, unchanged } = await copyChanged(ARCHIVE, target, names);
  console.log(
    `restore: ${target} — скопировано ${copied}, без изменений ${unchanged} (всего ${names.length})`,
  );
} else if (command === "save") {
  const source = flagValue(rest, "--source") ?? DEFAULT_TARGET;
  const names = await listPhotos(source);
  if (names.length === 0) {
    console.error(`В источнике нет фото: ${source}`);
    process.exit(1);
  }
  await mkdir(ARCHIVE, { recursive: true });
  const { copied, unchanged } = await copyChanged(source, ARCHIVE, names);
  console.log(
    `save: ${ARCHIVE} — скопировано ${copied}, без изменений ${unchanged} (всего ${names.length})`,
  );
} else {
  usage(`Неизвестная команда: ${command}`);
}

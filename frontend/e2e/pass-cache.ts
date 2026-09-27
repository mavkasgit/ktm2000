/**
 * Кеш «этот тест уже проходил на этой версии кода».
 *
 * Зачем
 * -----
 * Набор дорогой: широкий `@ui` — это ~15 минут, и полтора десятка из них
 * уходят на сценарии, которые на текущем коде уже зелёные. Повторный прогон
 * после неудачной правки должен гонять непроверенное и упавшее, а не всё
 * подряд.
 *
 * Версия кода
 * -----------
 * Ключ версии — коммит **плюс дифф рабочего дерева** (`git diff HEAD` и
 * список незакоммиченных файлов). Одного хеша коммита мало: в рабочем дереве
 * почти всегда есть незакоммиченные правки, и кеш по коммиту молча пропускал бы
 * тесты для кода, который никто не проверял.
 *
 * Что кеш НЕ делает
 * -----------------
 * - Не считает «зелёный» прогон зелёным: пропущенные по кешу тесты видны в
 *   отчёте как `skipped` с причиной, а решение «прогон засчитан» остаётся за
 *   полным прогоном без флага.
 * - Не переносит результат на другой коммит, другое окружение или другую
 *   правку: всё это входит в ключ версии.
 * - Не считает `skipped`/`timedOut`/`interrupted` прохождением: прошёл —
 *   значит последняя попытка `passed`.
 *
 * Формат хранения
 * ---------------
 * Файл — `frontend/.playwright/e2e-passed.json` (в `.gitignore`). Записи
 * хранятся как «последнее известное состояние с меткой времени», а не как
 * множество: под прогоном работает несколько worker-процессов, у каждого
 * своя память, и перезапись файла целиком откатывала бы результаты соседа
 * (тест, зелёный у первого воркера, исчезал после записи второго). Перед
 * записью файл перечитывается, по каждому ключу побеждает более свежая
 * запись.
 *
 * Включается флагом `E2E_SKIP_PASSED=1` (в CI не включается: там нужен
 * полный результат).
 */

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(E2E_DIR, "..");
const REPO_ROOT = path.resolve(E2E_DIR, "..", "..");
const CACHE_PATH = path.join(FRONTEND_DIR, ".playwright", "e2e-passed.json");

/** Меняется при несовместимой правке формата кеша — старый файл тогда игнор. */
const CACHE_FORMAT = 2;

function git(args: string[]): string | null {
  try {
    return execFileSync("git", args, {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      maxBuffer: 32 * 1024 * 1024,
    });
  } catch {
    return null;
  }
}

/**
 * Хеш версии кода. `null`, если git недоступен или это не репозиторий: тогда
 * кеш выключается целиком, а не «считается, что всё проходило».
 */
function resolveVersion(): string | null {
  const head = git(["rev-parse", "HEAD"]);
  if (!head) return null;
  const status = git(["status", "--porcelain=v1"]) ?? "";
  const diff = git(["diff", "HEAD"]) ?? "";
  return createHash("sha1")
    .update(`format=${CACHE_FORMAT}\nHEAD=${head.trim()}\nstatus=${status}\ndiff=${diff}`)
    .digest("hex");
}

interface CacheEntry {
  /** Метка времени: у ключей с одинаковым значением побеждает большая. */
  at: number;
  status: string;
}

interface CacheFile {
  format: number;
  version: string;
  entries: Record<string, CacheEntry>;
}

class PassCache {
  /** Кеш включается только флагом: по умолчанию прогон всегда полный. */
  readonly enabled = process.env.E2E_SKIP_PASSED === "1";

  private readonly version: string | null;
  private entries = new Map<string, CacheEntry>();
  private loaded = false;

  constructor() {
    this.version = this.enabled ? resolveVersion() : null;
    if (this.enabled && this.version === null) {
      console.log("[e2e:pass-cache] git недоступен — кеш выключен, прогон полный");
    }
  }

  /** Активен ли пропуск: флаг есть и версию удалось посчитать. */
  get active(): boolean {
    return this.enabled && this.version !== null;
  }

  /** Записи файла этой версии. Чужой формат/версия — пусто. */
  private readFile(): Record<string, CacheEntry> {
    try {
      const raw = JSON.parse(fs.readFileSync(CACHE_PATH, "utf8")) as CacheFile;
      if (raw.format === CACHE_FORMAT && raw.version === this.version && raw.entries) {
        return raw.entries;
      }
    } catch {
      // Файла нет или он не про этот формат/версию — начинаем с нуля.
    }
    return {};
  }

  private load(): void {
    if (this.loaded) return;
    this.loaded = true;
    this.entries = new Map(Object.entries(this.readFile()));
  }


  private write(key: string, entry: CacheEntry): void {
    if (this.version === null) return;
    // Перечитываем перед записью: соседний worker мог увидеть другой тест.
    const merged: Record<string, CacheEntry> = this.readFile();
    const known = merged[key];
    if (known && known.at > entry.at) return;
    merged[key] = entry;
    this.entries = new Map(Object.entries(merged));
    const payload: CacheFile = { format: CACHE_FORMAT, version: this.version, entries: merged };
    try {
      fs.mkdirSync(path.dirname(CACHE_PATH), { recursive: true });
      fs.writeFileSync(CACHE_PATH, `${JSON.stringify(payload, null, 2)}\n`);
    } catch (err) {
      console.log(`[e2e:pass-cache] не удалось записать кеш: ${(err as Error).message}`);
    }
  }

  /** Тест уже проходил на этой версии — его можно не гонять. */
  alreadyPassed(key: string): boolean {
    if (!this.active) return false;
    this.load();
    return this.entries.get(key)?.status === "passed";
  }

  /** Запомнить результат теста: зелёный — в кеш, остальное затирает его. */
  record(key: string, status: string): void {
    if (!this.active) return;
    this.load();
    this.write(key, { at: Date.now(), status });
  }

  /** Для диагностики: сколько тестов этой версии уже зелёные. */
  knownCount(): number {
    if (!this.active) return 0;
    this.load();
    let count = 0;
    for (const entry of this.entries.values()) {
      if (entry.status === "passed") count += 1;
    }
    return count;
  }
}

export const passCache = new PassCache();

/** Ключ теста: проект + полный путь заголовка (файл → describe → название). */
export function testCacheKey(project: string, titlePath: string[]): string {
  return `${project}:${titlePath.join(" › ")}`;
}

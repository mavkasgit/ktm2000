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
 * Ключ версии — коммит **плюс дифф рабочего дерева** (`git diff HEAD`,
 * `git status --porcelain=v1`) **плюс содержимое незакоммиченных (untracked)
 * файлов**. Одного хеша коммита мало: в рабочем дереве почти всегда есть
 * незакоммиченные правки, и кеш по коммиту молча пропускал бы тесты для кода,
 * который никто не проверял.
 *
 * Untracked-файлы в версию входят **содержимым**, а не путём: `git diff HEAD`
 * их не видит вообще, а `status --porcelain` сообщает только имя. Считать
 * одного «файл появился» было бы мало — агент правит новый файл без `git add`,
 * и все правки его содержимого после создания дали бы одну и ту же версию,
 * то есть молчаливо зелёный прогон на непроверенном коде.
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
 * Зелёный не с первой попытки
 * --------------------------
 * Запись с ретрая не выбрасывается: она попадает в кеш с пометкой
 * `passedOnRetry`, и такой тест **не пропускается** в следующем прогоне,
 * пока не пройдёт чисто с первой попытки. Пометка снимается сама, когда
 * тест зелёный на первой попытке (запись перезаписывается) или снова красный.
 * Смысл: результат зелёный, но «прошёл с первой попытки» — нет, а кеш
 * существует ради второго. Раньше ретрайная попытка просто не записывалась,
 * и флейк на этой же версии кода оставался в кеше зелёным навсегда.
 *
 * Видимость флейка в самом прогоне — отдельная история: её даёт репортер
 * [`green-on-retry-reporter.ts`](green-on-retry-reporter.ts), потому что
 * прогон с `retries: 2` в CI иначе выглядит зелёным ровно как чистый.
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
const CACHE_FORMAT = 3;

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
  const untracked = resolveUntrackedContents();
  if (untracked === null) return null;
  return createHash("sha1")
    .update(
      `format=${CACHE_FORMAT}\nHEAD=${head.trim()}\nstatus=${status}\ndiff=${diff}\nuntracked=${untracked}`,
    )
    .digest("hex");
}

/**
 * Содержимое всех незакоммиченных файлов, отсортированное по пути и
 * склеенное в одну строку. `null` — git недоступен или список не читается:
 * тогда версию не считаем вовсе, чтобы не «прошёл мимо» ни одного файла.
 */
function resolveUntrackedContents(): string | null {
  const listing = git(["ls-files", "--others", "--exclude-standard"]);
  if (listing === null) return null;
  const parts: string[] = [];
  for (const relPath of listing.split("\n").map((line) => line.trim()).filter(Boolean).sort()) {
    const abs = path.resolve(REPO_ROOT, relPath);
    let content: Buffer;
    try {
      content = fs.readFileSync(abs);
    } catch {
      // Файл исчез между `ls-files` и чтением (или это не файл) — версия
      // неполна, кеш лучше не включать, чем считать проверенным не всё дерево.
      return null;
    }
    parts.push(`${relPath}:${createHash("sha1").update(content).digest("hex")}`);
  }
  return parts.join("\n");
}

interface CacheEntry {
  /** Метка времени: у ключей с одинаковым значением побеждает большая. */
  at: number;
  status: string;
  /**
   * Зелёный, но не с первой попытки: первая попытка была красной, вторая —
   * зелёной. Такой тест НЕ пропускается в следующем прогоне, пока не
   * пройдёт чисто: иначе флейк, однажды попав в кеш, молча выпадал бы из
   * проверки навсегда.
   */
  passedOnRetry?: boolean;
}

interface CacheFile {
  format: number;
  version: string;
  entries: Record<string, CacheEntry>;
}

export interface PassCacheOptions {
  /** Файл кеша; по умолчанию — боевой `.playwright/e2e-passed.json`. */
  file?: string;
  /** Версия кода; по умолчанию — хеш git. `null` оставляет кеш выключенным. */
  version?: string | null;
  /** Проброс флага `E2E_SKIP_PASSED` мимо окружения (юнит-тест). */
  enabled?: boolean;
}

export class PassCache {
  /** Кеш включается только флагом: по умолчанию прогон всегда полный. */
  readonly enabled: boolean;

  private readonly version: string | null;
  private readonly file: string;
  private entries = new Map<string, CacheEntry>();
  private loaded = false;

  constructor(options: PassCacheOptions = {}) {
    this.enabled = options.enabled ?? process.env.E2E_SKIP_PASSED === "1";
    this.file = options.file ?? CACHE_PATH;
    // Версию считаем только при включённом кеше: git зовётся зря, когда флага нет.
    if (!this.enabled) this.version = null;
    else if (options.version !== undefined) this.version = options.version;
    else this.version = resolveVersion();
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
      const raw = JSON.parse(fs.readFileSync(this.file, "utf8")) as CacheFile;
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
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file, `${JSON.stringify(payload, null, 2)}\n`);
    } catch (err) {
      console.log(`[e2e:pass-cache] не удалось записать кеш: ${(err as Error).message}`);
    }
  }

  /**
   * Тест уже проходил на этой версии — его можно не гонять.
   *
   * Зелёный с ретрая сюда НЕ попадает: такая запись помечена `passedOnRetry`,
   * и пока флейк не пройдёт чисто с первой попытки, прогон гоняет его снова.
   * Иначе кеш превращал бы флейк в «проверенный» результат — ровно то
   * маскирование, ради которого ретрай и не записывается вслепую.
   */
  alreadyPassed(key: string): boolean {
    if (!this.active) return false;
    this.load();
    const entry = this.entries.get(key);
    return entry?.status === "passed" && !entry.passedOnRetry;
  }

  /**
   * Запомнить результат теста: зелёный — в кеш, остальное затирает его.
   *
   * `retry` — номер попытки, нумерация с 0. Зелёный результат попытки с
   * ретраем записывается, но с пометкой `passedOnRetry`: результат настоящий,
   * а вот «прошло с первой попытки» — нет, и кеш обязан это различать.
   */
  record(key: string, status: string, retry = 0): void {
    if (!this.active) return;
    this.load();
    this.write(key, {
      at: Date.now(),
      status,
      ...(retry > 0 && status === "passed" ? { passedOnRetry: true } : {}),
    });
  }

  /** Для диагностики: сколько тестов этой версии реально будут пропущены. */
  knownCount(): number {
    if (!this.active) return 0;
    this.load();
    let count = 0;
    for (const entry of this.entries.values()) {
      if (entry.status === "passed" && !entry.passedOnRetry) count += 1;
    }
    return count;
  }
}

export const passCache = new PassCache();

/** Ключ теста: проект + полный путь заголовка (файл → describe → название). */
export function testCacheKey(project: string, titlePath: string[]): string {
  return `${project}:${titlePath.join(" › ")}`;
}

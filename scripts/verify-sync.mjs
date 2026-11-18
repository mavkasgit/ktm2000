/**
 * Синк-гейт переносимых файлов между sibling-проектами HRMS/KTM.
 *
 * Сверяет файлы, помеченные в scripts/sync-manifest.json как must-match.
 * Синхронизация ручная: после правки общего файла агент переносит копию
 * в соседний проект и поднимает версию.
 *
 * Режимы сравнения (поле entry.mode):
 *   - content  — байт-эквивалент, переводы строк (CRLF/LF) игнорируются;
 *   - version  — совпадение констант *_VERSION (или поля "version" в JSON)
 *                из хостового файла директории (для файла — сам файл);
 *   - presence — файл обязан существовать в обоих проектах, содержимое
 *                может различаться (хостовые файлы модулей, напр. ui.ts).
 * Поле entry.version:true добавляет к content-сравнению сверку версии.
 *
 * Запуск (из корня репозитория):
 *   node scripts/verify-sync.mjs --other ../hrms
 *   node scripts/verify-sync.mjs --other ../hrms --baseline scripts/sync-baseline.json
 *   node scripts/verify-sync.mjs --other ../hrms --if-enabled
 *   node scripts/verify-sync.mjs --other ../hrms --baseline ... --optional
 *   node scripts/verify-sync.mjs --other ../hrms --baseline ... --update-baseline
 *
 * Baseline (JSON `{ "version": 2, "entries": [...] }`) — снимок уже известных
 * расхождений. Запись фиксирует не только путь, но и вид находки с содержимым:
 *
 *   { "path": "...", "kind": "content", "hash": "<sha256 локального файла>",
 *     "reason": "...", "reviewed": "2026-11-18", "expires": "2027-06-30" }
 *
 * Сравнение идёт по path+kind+hash. Иначе запись «подавляет путь целиком» и
 * новое ухудшение на известном пути (правка useAuth.tsx) проходит зелёным —
 * ровно этот дефект и закрывает снимок содержимого. Изменился локальный
 * файл — hash другой, прогон красный: изменение подтверждают и пересобирают
 * снимок осознанно, а не «оно и так в baseline».
 *
 * hash — sha256 нормализованного содержимого (CRLF/LF не различаются, как и
 * в самом сравнении). Sentinel `none` — локального содержимого нет вовсе:
 * «файл есть у соседа, но отсутствует здесь» или нет хостового файла версии.
 * У находки «файл есть здесь, но отсутствует у соседа» hash берётся: локальный
 * файл существует, и его правка обязана ломать прогон (иначе baseline снова
 * подавляет ухудшение). Для presence-режима расхождения содержимым не
 * считаются, поэтому отдельных находок он не даёт — только missing-here/
 * missing-there.
 *
 * reviewed/expires — дата снимка и дата пересмотра долга (2027-06-30).
 * Отсутствие или неверный формат любого поля — exit 2 (ошибка конфигурации):
 * baseline без срока и содержимого — это «выключить проверку», а не долг.
 *
 * Записи, которых больше нет среди находок, печатаются как `stale`
 * (не падение) — чтобы долг убирали, а не копили. `--strict` baseline
 * игнорирует: так проверяют, что долг закрыт.
 *
 * `--update-baseline` пересобирает снимок по текущему прогону (reason
 * сохраняется у совпавших записей). Это осознанное действие человека:
 * сначала проверка красная, потом снимок обновляют.
 *
 * `--optional` — только для хука/локального окружения без соседа: если
 * `--other` не существует, печатается причина и exit 0. Ручной
 * `npm run verify:sync` остаётся строгим (exit 2).
 *
 * В автоматическом режиме (`--if-enabled`) проверка выполняется только при
 * KTM_SYNCGATE=1|true|yes|on. Без переменной выход успешный, с неверным
 * значением — ошибка. Ручной запуск без флага проверяет всегда.
 */
import fs from "node:fs"
import path from "node:path"
import { createHash } from "node:crypto"
import { fileURLToPath } from "node:url"

export const SYNC_VERSION = "1.3.0"

/** Дата пересмотра известного долга; после неё baseline пересматривают. */
export const BASELINE_EXPIRES = "2027-06-30"

/** Виды находок, которые база может подавлять. */
export const FINDING_KINDS = ["content", "version", "missing-here", "missing-there"]

/** Локального содержимого нет — хешировать нечего. */
export const NO_LOCAL_HASH = "none"

const MANIFEST = "scripts/sync-manifest.json"
const HOST_NAMES = ["index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"]
const MODES = new Set(["content", "version", "presence"])
const VERSION_RE = /(?:export\s+)?const\s+([A-Z][A-Z0-9_]*_VERSION)\s*=\s*["']([^"']+)["']/g
const SHA256_RE = /^[0-9a-f]{64}$/
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

const ENABLED_VALUES = new Set(["1", "true", "yes", "on"])

export function parseArgs(argv) {
  const args = {
    other: null,
    root: null,
    ifEnabled: false,
    baseline: null,
    strict: false,
    optional: false,
    updateBaseline: false,
  }
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--other" && argv[i + 1]) {
      args.other = argv[i + 1]
      i++
    } else if (argv[i] === "--root" && argv[i + 1]) {
      args.root = argv[i + 1]
      i++
    } else if (argv[i] === "--baseline" && argv[i + 1]) {
      args.baseline = argv[i + 1]
      i++
    } else if (argv[i] === "--if-enabled") {
      args.ifEnabled = true
    } else if (argv[i] === "--strict") {
      args.strict = true
    } else if (argv[i] === "--optional" || argv[i] === "--skip-if-missing") {
      args.optional = true
    } else if (argv[i] === "--update-baseline") {
      args.updateBaseline = true
    }
  }
  return args
}

export function normalize(content) {
  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}

/** sha256 нормализованного содержимого: CRLF/LF — не изменение. */
export function hashContent(content) {
  return createHash("sha256").update(normalize(content), "utf8").digest("hex")
}

export function extractVersions(content, filePath) {
  const versions = new Map()
  if (path.extname(filePath).toLowerCase() === ".json") {
    try {
      const parsed = JSON.parse(content)
      if (typeof parsed?.version === "string") versions.set("version", parsed.version)
    } catch {
      // не JSON — версий нет
    }
    return versions
  }
  for (const match of content.matchAll(VERSION_RE)) versions.set(match[1], match[2])
  return versions
}

function hostFileFor(rel, root) {
  const abs = path.join(root, rel)
  if (!fs.existsSync(abs)) return null
  if (fs.statSync(abs).isFile()) return abs
  for (const name of HOST_NAMES) {
    const candidate = path.join(abs, name)
    if (fs.existsSync(candidate)) return candidate
  }
  return null
}

/** hash локального файла (для директории — хостового index.*), иначе sentinel. */
function localHash(rel, root) {
  const host = hostFileFor(rel, root)
  if (!host) return NO_LOCAL_HASH
  try {
    return hashContent(fs.readFileSync(host, "utf8"))
  } catch {
    return NO_LOCAL_HASH
  }
}

function compareVersions(fileA, fileB, rel) {
  const errors = []
  const a = normalize(fs.readFileSync(fileA, "utf8"))
  const b = normalize(fs.readFileSync(fileB, "utf8"))
  const va = extractVersions(a, fileA)
  const vb = extractVersions(b, fileB)
  const keys = new Set([...va.keys(), ...vb.keys()])
  if (keys.size === 0) {
    errors.push(`не найдены константы *_VERSION: ${rel}`)
    return errors
  }
  for (const key of keys) {
    if (va.get(key) !== vb.get(key)) {
      errors.push(
        `version mismatch: ожидалось ${va.get(key) ?? "—"}, у соседа ${vb.get(key) ?? "—"} (${rel}: ${key})`,
      )
    }
  }
  return errors
}

function baselineKey(rel, kind, hash) {
  return `${rel}\u0000${kind}\u0000${hash}`
}

function isIsoDate(value) {
  if (typeof value !== "string" || !ISO_DATE_RE.test(value)) return false
  return !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
}

/**
 * Читает baseline. Возвращает либо Map path+kind+hash → запись, либо { error }.
 * Битый, неполный или отсутствующий файл — ошибка конфигурации (exit 2),
 * а не расхождение: иначе «нет файла = всё совпало».
 */
export function loadBaseline(absPath) {
  let raw
  try {
    raw = fs.readFileSync(absPath, "utf8")
  } catch (error) {
    return { error: `baseline не читается: ${absPath} (${error.message})` }
  }
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (error) {
    return { error: `baseline не JSON: ${absPath} (${error.message})` }
  }
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.entries)) {
    return { error: `baseline не содержит массив entries: ${absPath}` }
  }
  const entries = new Map()
  for (const [index, entry] of parsed.entries.entries()) {
    if (!entry || typeof entry !== "object" || typeof entry.path !== "string" || entry.path.trim() === "") {
      return { error: `baseline: запись #${index} без строкового path: ${absPath}` }
    }
    const rel = entry.path.trim()
    if (!FINDING_KINDS.includes(entry.kind)) {
      return {
        error: `baseline: запись #${index} (${rel}) без поля kind или неизвестный kind ${JSON.stringify(entry.kind)} (ожидается: ${FINDING_KINDS.join(", ")}) — пересоберите снимок с --update-baseline`,
      }
    }
    if (entry.hash !== NO_LOCAL_HASH && (typeof entry.hash !== "string" || !SHA256_RE.test(entry.hash))) {
      return {
        error: `baseline: запись #${index} (${rel}) без поля hash (sha256) или с невалидным значением — пересоберите снимок с --update-baseline`,
      }
    }
    if (!isIsoDate(entry.reviewed)) {
      return { error: `baseline: запись #${index} (${rel}) без поля reviewed (ГГГГ-ММ-ДД): ${absPath}` }
    }
    if (!isIsoDate(entry.expires)) {
      return { error: `baseline: запись #${index} (${rel}) без поля expires (ГГГГ-ММ-ДД): ${absPath}` }
    }
    if (entry.expires < entry.reviewed) {
      return { error: `baseline: запись #${index} (${rel}) истекает раньше, чем пересмотрена: ${absPath}` }
    }
    const reason = typeof entry.reason === "string" && entry.reason.trim() ? entry.reason.trim() : "без причины"
    const key = baselineKey(rel, entry.kind, entry.hash)
    if (entries.has(key)) {
      return { error: `baseline: дубль записи ${rel} [${entry.kind}] с тем же hash: ${absPath}` }
    }
    entries.set(key, {
      path: rel,
      kind: entry.kind,
      hash: entry.hash,
      reason,
      reviewed: entry.reviewed,
      expires: entry.expires,
    })
  }
  return { entries }
}

export function run({ root, otherRoot, manifestPath = MANIFEST, baselinePath = null, strict = false }) {
  const manifestFile = path.join(root, manifestPath)
  let manifest
  try {
    manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"))
  } catch (error) {
    return {
      ok: false,
      errors: [`Не удалось прочитать манифест: ${manifestFile} (${error.message})`],
      known: [],
      stale: [],
      problems: [],
      checked: 0,
      exitCode: 1,
    }
  }
  const entries = manifest.files
  if (!Array.isArray(entries) || entries.length === 0) {
    return {
      ok: false,
      errors: [`манифест пуст или не содержит files: ${manifestFile}`],
      known: [],
      stale: [],
      problems: [],
      checked: 0,
      exitCode: 1,
    }
  }
  const problems = []
  let checked = 0
  const report = (message, rel, kind, hash = NO_LOCAL_HASH) =>
    problems.push({ path: rel, message, kind, hash })
  const reportConfig = (message, rel) => problems.push({ path: rel, message, kind: "config" })

  for (const entry of entries) {
    const rel = entry.path
    const mode = entry.mode ?? "content"
    if (!MODES.has(mode)) {
      reportConfig(`неизвестный режим сравнения: ${mode} (${rel})`, rel)
      continue
    }
    const hereAbs = path.join(root, rel)
    const thereAbs = path.join(otherRoot, rel)
    if (!fs.existsSync(hereAbs)) {
      report(`файл есть у соседа, но отсутствует здесь: ${rel}`, rel, "missing-here")
      continue
    }
    if (!fs.existsSync(thereAbs)) {
      // Локальный файл есть — фиксируем его содержимое, иначе правка на этом
      // пути снова проходит незамеченной (см. шапку про path+kind+hash).
      report(`файл есть здесь, но отсутствует у соседа: ${rel}`, rel, "missing-there", localHash(rel, root))
      continue
    }
    if (mode === "presence") {
      checked++
      continue
    }
    if (mode === "version") {
      const hereHost = hostFileFor(rel, root)
      const thereHost = hostFileFor(rel, otherRoot)
      if (!hereHost || !thereHost) {
        report(`не найден хостовый файл версии: ${rel}`, rel, "version", localHash(rel, root))
        continue
      }
      const hash = hashContent(fs.readFileSync(hereHost, "utf8"))
      for (const message of compareVersions(hereHost, thereHost, rel)) report(message, rel, "version", hash)
      checked++
      continue
    }
    const hash = hashContent(fs.readFileSync(hereAbs, "utf8"))
    const a = normalize(fs.readFileSync(hereAbs, "utf8"))
    const b = normalize(fs.readFileSync(thereAbs, "utf8"))
    if (a !== b) {
      report(`hash mismatch: файл изменён без поднятия версии: ${rel}`, rel, "content", hash)
    }
    if (entry.version) {
      for (const message of compareVersions(hereAbs, thereAbs, rel)) report(message, rel, "version", hash)
    }
    checked++
  }

  if (strict) {
    const errors = problems.map((problem) => problem.message)
    return {
      ok: errors.length === 0,
      errors,
      known: [],
      stale: [],
      problems,
      checked,
      exitCode: errors.length === 0 ? 0 : 1,
    }
  }

  let baseline = null
  if (baselinePath) {
    const loaded = loadBaseline(baselinePath)
    if (loaded.error) {
      return {
        ok: false,
        errors: [loaded.error],
        known: [],
        stale: [],
        problems,
        checked,
        exitCode: 2,
      }
    }
    baseline = loaded.entries
  }

  const errors = []
  const known = []
  const used = new Set()
  const seen = new Set()
  for (const problem of problems) {
    if (problem.kind === "config") {
      errors.push(problem.message)
      continue
    }
    seen.add(`${problem.path}\u0000${problem.kind}`)
    const key = baselineKey(problem.path, problem.kind, problem.hash)
    const record = baseline?.get(key)
    if (record) {
      known.push({ path: problem.path, kind: problem.kind, message: problem.message, reason: record.reason })
      used.add(key)
      continue
    }
    const sameKind = baseline
      ? [...baseline.entries()].find(
          ([, record]) => record.path === problem.path && record.kind === problem.kind,
        )
      : undefined
    if (sameKind) {
      errors.push(
        `${problem.message} — файл изменился с момента снимка baseline (${problem.path} [${problem.kind}], hash ${problem.hash.slice(0, 12)}…). Проверьте изменение и пересоберите снимок: --update-baseline`,
      )
      continue
    }
    errors.push(problem.message)
  }
  const stale = baseline
    ? [...baseline.entries()]
        .filter(
          ([key, record]) =>
            !used.has(key) && !seen.has(`${record.path}\u0000${record.kind}`),
        )
        .map(([, record]) => record)
    : []

  return {
    ok: errors.length === 0,
    errors,
    known,
    stale,
    problems,
    checked,
    exitCode: errors.length === 0 ? 0 : 1,
  }
}

/**
 * Причины из снимка прежнего формата (path+reason без kind/hash): нужны, чтобы
 * пересборка не превращала объяснённый долг в «не объяснено». Формат не
 * валидируется — это только источник текста, авторитет у нового снимка.
 */
export function legacyReasons(absPath) {
  const reasons = new Map()
  try {
    const parsed = JSON.parse(fs.readFileSync(absPath, "utf8"))
    for (const entry of parsed?.entries ?? []) {
      if (
        entry &&
        typeof entry.path === "string" &&
        typeof entry.reason === "string" &&
        entry.reason.trim()
      ) {
        reasons.set(entry.path.trim(), entry.reason.trim())
      }
    }
  } catch {
    // старого снимка нет или он битый — причин взять неоткуда
  }
  return reasons
}

/** Снимок по текущим находкам; reason сохраняется у совпавшей записи. */
export function buildBaseline(problems, previous = new Map(), reviewed = today(), legacyReasons = new Map()) {
  const byKey = new Map()
  for (const problem of problems) {
    if (problem.kind === "config") continue
    const key = baselineKey(problem.path, problem.kind, problem.hash)
    if (byKey.has(key)) continue
    const kept =
      previous.get(key) ??
      [...previous.values()].find(
        (record) => record.path === problem.path && record.kind === problem.kind,
      )
    byKey.set(key, {
      path: problem.path,
      kind: problem.kind,
      hash: problem.hash,
      reason:
        kept?.reason ??
        legacyReasons.get(problem.path) ??
        "не объяснено при пересборке baseline",
      reviewed,
      expires: BASELINE_EXPIRES,
    })
  }
  return [...byKey.values()].sort(
    (a, b) => a.path.localeCompare(b.path) || a.kind.localeCompare(b.kind),
  )
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function main() {
  const {
    other,
    root: rootOverride,
    ifEnabled,
    baseline,
    strict,
    optional,
    updateBaseline,
  } = parseArgs(process.argv.slice(2))
  if (!other) {
    console.error(
      "Использование: node scripts/verify-sync.mjs --other <путь к sibling-проекту> [--root <корень репозитория>] [--baseline <файл>] [--strict] [--if-enabled] [--optional] [--update-baseline]",
    )
    process.exit(2)
  }
  if (ifEnabled) {
    const value = process.env.KTM_SYNCGATE
    if (value === undefined) {
      console.log("Синк-гейт отключён (KTM_SYNCGATE не установлен).")
      process.exit(0)
    }
    const normalized = value.trim().toLowerCase()
    if (!ENABLED_VALUES.has(normalized)) {
      console.error(
        `Недопустимое значение KTM_SYNCGATE=${JSON.stringify(value)}. Используйте одно из: 1, true, yes, on.`,
      )
      process.exit(2)
    }
  }
  const root = rootOverride
    ? path.resolve(rootOverride)
    : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
  const otherRoot = path.resolve(root, other)
  if (!fs.existsSync(otherRoot)) {
    const reason = `sibling-проект не найден: ${otherRoot}. Проверка идёт из корня клона, где сосед существует (локально — ../hrms, в CI — отдельный checkout).`
    if (optional) {
      console.log(`Синк-гейт пропущен (--optional): ${reason}`)
      process.exit(0)
    }
    console.error(reason)
    process.exit(2)
  }
  const baselinePath = baseline ? path.resolve(root, baseline) : null

  if (updateBaseline) {
    if (!baselinePath) {
      console.error("--update-baseline требует --baseline <файл>: путь к пересобираемому снимку.")
      process.exit(2)
    }
    const previous = loadBaseline(baselinePath)
    const result = run({ root, otherRoot, strict: true })
    const config = result.problems.filter((problem) => problem.kind === "config")
    if (config.length) {
      for (const problem of config) console.error(problem.message)
      console.error("Baseline не пересобран: сначала почините конфигурацию манифеста.")
      process.exit(2)
    }
    const entries = buildBaseline(
      result.problems,
      previous.error ? new Map() : previous.entries,
      today(),
      previous.error ? legacyReasons(baselinePath) : new Map(),
    )
    fs.writeFileSync(baselinePath, `${JSON.stringify({ version: 2, entries }, null, 2)}\n`)
    console.log(
      `Baseline пересобран: ${entries.length} записей, reviewed ${today()}, expires ${BASELINE_EXPIRES} (${baselinePath}).`,
    )
    process.exit(0)
  }

  const result = run({ root, otherRoot, baselinePath, strict })
  for (const item of result.known) {
    console.log(`known: ${item.path} [${item.kind}] — ${item.reason} (${item.message})`)
  }
  for (const record of result.stale) {
    console.log(`stale: ${record.path} [${record.kind}] — запись baseline больше не нужна`)
  }
  for (const error of result.errors) console.error(error)
  if (result.ok) {
    const knownNote = result.known.length ? `, ${result.known.length} известных по baseline` : ""
    console.log(
      `Синк-гейт пройден: ${result.checked} файлов совпадают (${path.basename(otherRoot)})${knownNote}.`,
    )
    process.exit(0)
  }
  console.error("Синк-гейт НЕ пройден.")
  process.exit(result.exitCode ?? 1)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main()
}

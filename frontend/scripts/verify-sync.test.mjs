import { afterEach, describe, expect, it } from "vitest"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import {
  SYNC_VERSION,
  extractVersions,
  normalize,
  parseArgs,
  run,
} from "../../scripts/verify-sync.mjs"

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const SCRIPT = path.join(REPO_ROOT, "scripts/verify-sync.mjs")

function envWithoutSyncgate() {
  const env = { ...process.env }
  delete env.KTM_SYNCGATE
  return env
}

const tempDirs = []

function makeTree(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "verify-sync-"))
  tempDirs.push(dir)
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel)
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, content)
  }
  return dir
}

afterEach(() => {
  while (tempDirs.length) fs.rmSync(tempDirs.pop(), { recursive: true, force: true })
})

const HOST = `export const DEMO_VERSION = "1.2.3"\n`
const SELF = `export const SYNC_VERSION = "${SYNC_VERSION}"\nconsole.log("ok")\n`

function manifest(files) {
  return JSON.stringify({ version: "1.0.0", files }, null, 2)
}

const BASE_MANIFEST = manifest([
  { path: "shared/file.txt", mode: "content" },
  { path: "mod/index.ts", mode: "version" },
  { path: "host/ui.ts", mode: "presence" },
  { path: "scripts/verify-sync.mjs", mode: "content", version: true },
  { path: "scripts/sync-manifest.json", mode: "content", version: true },
])

function baseTree() {
  return {
    "shared/file.txt": "общий файл\n",
    "mod/index.ts": HOST,
    "host/ui.ts": "хост: содержимое может отличаться\n",
    "scripts/verify-sync.mjs": SELF,
    "scripts/sync-manifest.json": BASE_MANIFEST,
  }
}

describe("verify-sync.mjs", () => {
  it("normalize игнорирует CRLF", () => {
    expect(normalize("a\r\nb\rc\n")).toBe("a\nb\nc\n")
  })

  it("parseArgs извлекает --other, --root, --if-enabled, --baseline и --strict", () => {
    expect(parseArgs(["node", "x", "--other", "../hrms"])).toEqual({
      other: "../hrms",
      root: null,
      ifEnabled: false,
      baseline: null,
      strict: false,
    })
    expect(parseArgs(["node", "x", "--root", "/tmp/a", "--other", "../hrms", "--if-enabled"])).toEqual({
      other: "../hrms",
      root: "/tmp/a",
      ifEnabled: true,
      baseline: null,
      strict: false,
    })
    expect(
      parseArgs([
        "node",
        "x",
        "--other",
        "../hrms",
        "--baseline",
        "scripts/sync-baseline.json",
        "--strict",
      ]),
    ).toEqual({
      other: "../hrms",
      root: null,
      ifEnabled: false,
      baseline: "scripts/sync-baseline.json",
      strict: true,
    })
    expect(parseArgs([])).toEqual({
      other: null,
      root: null,
      ifEnabled: false,
      baseline: null,
      strict: false,
    })
  })

  it("--if-enabled без KTM_SYNCGATE пропускает проверку", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
      { cwd: root, encoding: "utf8", env: envWithoutSyncgate() },
    )

    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("Синк-гейт отключён")
    expect(spawned.stdout).not.toContain("Синк-гейт пройден")
  })

  it.each(["1", "TrUe", "YeS", "oN"])(
    "--if-enabled с KTM_SYNCGATE=%s выполняет проверку независимо от регистра",
    (value) => {
      const root = makeTree(baseTree())
      const otherTree = baseTree()
      otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
      const other = makeTree(otherTree)
      const spawned = spawnSync(
        process.execPath,
        [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
        { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: value } },
      )

      expect(spawned.status).toBe(1)
      expect(spawned.stderr).toContain("version mismatch")
    },
  )

  it("--if-enabled с недопустимым KTM_SYNCGATE завершается с кодом 2", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
      { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: "maybe" } },
    )

    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("1, true, yes, on")
  })

  it("ручной режим игнорирует KTM_SYNCGATE", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other],
      { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: "maybe" } },
    )

    expect(spawned.status).toBe(1)
    expect(spawned.stderr).toContain("version mismatch")
  })

  it("extractVersions читает *_VERSION и version из JSON", () => {
    const content = 'export const FOO_VERSION = "2.0.0"\nexport const BAR_VERSION = "1.0.0"\n'
    expect(extractVersions(content, "index.ts")).toEqual(
      new Map([
        ["FOO_VERSION", "2.0.0"],
        ["BAR_VERSION", "1.0.0"],
      ]),
    )
    expect(extractVersions('{ "version": "3.0.0" }', "manifest.json").get("version")).toBe("3.0.0")
  })

  it("match → ok (exit 0)", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.checked).toBe(5)

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(0)
  })

  it("version-mismatch → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("version mismatch")
    expect(result.errors.join("\n")).toContain("ожидалось 1.2.3")
    expect(result.errors.join("\n")).toContain("у соседа 9.9.9")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("hash-mismatch → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("hash mismatch")
    expect(result.errors.join("\n")).toContain("изменён без поднятия версии")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("self-check: расхождение verify-sync.mjs/манифеста тоже валит (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["scripts/verify-sync.mjs"] = 'export const SYNC_VERSION = "0.9.0"\nconsole.log("edited")\n'
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("hash mismatch")
    expect(result.errors.join("\n")).toContain("version mismatch")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("version mode поддерживает хостовый файл директории (index.*)", () => {
    const files = baseTree()
    files["scripts/sync-manifest.json"] = manifest([
      { path: "mod", mode: "version" },
      { path: "scripts/verify-sync.mjs", mode: "content", version: true },
      { path: "scripts/sync-manifest.json", mode: "content", version: true },
    ])
    const root = makeTree(files)
    const otherTree = { ...files }
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("version mismatch")
  })

  it("неизвестный mode → fail", () => {
    const files = baseTree()
    files["scripts/sync-manifest.json"] = manifest([{ path: "mod/index.ts", mode: "checksum" }])
    const root = makeTree(files)
    const other = makeTree(files)
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("неизвестный режим")
  })

  it("пустой манифест без files → fail", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    fs.writeFileSync(path.join(root, "scripts/sync-manifest.json"), JSON.stringify({ version: "1.0.0" }))
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("не содержит files")
  })

  it("version mode без констант *_VERSION → fail", () => {
    const files = baseTree()
    files["mod/index.ts"] = "export const PI = 3.14\n"
    files["scripts/sync-manifest.json"] = manifest([{ path: "mod/index.ts", mode: "version" }])
    const root = makeTree(files)
    const otherTree = { ...files }
    otherTree["mod/index.ts"] = "export const PI = 3.14\nexport const E = 2.71\n"
    const other = makeTree(otherTree)
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("не найдены константы *_VERSION")
  })

  it("отсутствующий файл у соседа → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    delete otherTree["mod/index.ts"]
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("отсутствует у соседа")
  })

  it("presence mode: содержимое может различаться, файл обязан существовать", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["host/ui.ts"] = "другой хост: свои импорты\n"
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.checked).toBe(5)
  })

  it("presence mode: отсутствующий файл → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    delete otherTree["host/ui.ts"]
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("файл есть здесь, но отсутствует у соседа")
  })

  it("presence mode: файл есть у соседа, но отсутствует здесь → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    const other = makeTree(otherTree)
    fs.unlinkSync(path.join(root, "host/ui.ts"))

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("файл есть у соседа, но отсутствует здесь")
  })
})

const BASELINE = "scripts/sync-baseline.json"

function writeBaseline(root, entries) {
  const abs = path.join(root, BASELINE)
  fs.mkdirSync(path.dirname(abs), { recursive: true })
  fs.writeFileSync(abs, typeof entries === "string" ? entries : JSON.stringify({ entries }, null, 2))
}

function runCli(root, other, extra = []) {
  return spawnSync(
    process.execPath,
    [SCRIPT, "--root", root, "--other", other, "--baseline", BASELINE, ...extra],
    { cwd: root, encoding: "utf8" },
  )
}

describe("verify-sync.mjs: baseline", () => {
  it("известное расхождение подавляется и печатается как known (exit 0)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    writeBaseline(root, [
      { path: "shared/file.txt", reason: "auth/OIDC debt (ADR/spec: retro 2026-11-18)" },
    ])

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.known.map((k) => k.path)).toEqual(["shared/file.txt"])

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("known")
    expect(spawned.stdout).toContain("shared/file.txt")
    expect(spawned.stdout).toContain("Синк-гейт пройден")
  })

  it("новое расхождение вне baseline → fail, подавленное не мешает", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)
    writeBaseline(root, [
      { path: "shared/file.txt", reason: "auth/OIDC debt (ADR/spec: retro 2026-11-18)" },
    ])

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(false)
    expect(result.known.map((k) => k.path)).toEqual(["shared/file.txt"])
    expect(result.errors.join("\n")).toContain("mod/index.ts")
    expect(result.errors.join("\n")).not.toContain("shared/file.txt")

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(1)
    expect(spawned.stderr).toContain("mod/index.ts")
  })

  it("--strict игнорирует baseline → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    writeBaseline(root, [
      { path: "shared/file.txt", reason: "auth/OIDC debt (ADR/spec: retro 2026-11-18)" },
    ])

    const result = run({
      root,
      otherRoot: other,
      baselinePath: path.join(root, BASELINE),
      strict: true,
    })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("shared/file.txt")

    const spawned = runCli(root, other, ["--strict"])
    expect(spawned.status).toBe(1)
  })

  it("неиспользованная запись baseline печатается как stale и не валит (exit 0)", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    writeBaseline(root, [{ path: "shared/file.txt", reason: "долг закрыт" }])

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("stale")
    expect(spawned.stdout).toContain("shared/file.txt")
  })

  it.each([
    ["отсутствует", null],
    ["не JSON", "{ это не json"],
    ["нет entries", JSON.stringify({ files: [] })],
    ["entries не массив", JSON.stringify({ entries: {} })],
    ["запись без path", JSON.stringify({ entries: [{ reason: "нет пути" }] })],
  ])("битый baseline (%s) → exit 2", (_label, content) => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    if (content !== null) writeBaseline(root, content)

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(false)
    expect(result.exitCode).toBe(2)

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("baseline")
  })

  it("--strict не читает baseline: отсутствующий файл не мешает", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())

    const spawned = runCli(root, other, ["--strict"])
    expect(spawned.status).toBe(0)
  })

  it("отсутствующий sibling-проект → exit 2 с внятной причиной", () => {
    const root = makeTree(baseTree())
    const missing = path.join(root, "нет-такого-соседа")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", missing], {
      cwd: root,
      encoding: "utf8",
    })
    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("sibling-проект не найден")
  })
})

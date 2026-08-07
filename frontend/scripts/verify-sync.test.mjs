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
  { path: "scripts/verify-sync.mjs", mode: "content", version: true },
  { path: "scripts/sync-manifest.json", mode: "content", version: true },
])

function baseTree() {
  return {
    "shared/file.txt": "общий файл\n",
    "mod/index.ts": HOST,
    "scripts/verify-sync.mjs": SELF,
    "scripts/sync-manifest.json": BASE_MANIFEST,
  }
}

describe("verify-sync.mjs", () => {
  it("normalize игнорирует CRLF", () => {
    expect(normalize("a\r\nb\rc\n")).toBe("a\nb\nc\n")
  })

  it("parseArgs извлекает --other и --root", () => {
    expect(parseArgs(["node", "x", "--other", "../hrms"])).toEqual({ other: "../hrms", root: null })
    expect(parseArgs(["node", "x", "--root", "/tmp/a", "--other", "../hrms"])).toEqual({
      other: "../hrms",
      root: "/tmp/a",
    })
    expect(parseArgs([])).toEqual({ other: null, root: null })
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
    expect(result.checked).toBe(4)

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
})

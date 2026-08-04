/**
 * Сквозная проверка контура иконок: backend-имена → lucide-react.
 *
 * Имя иконки хранится строкой в бэкенд-сидах/тестах, отдаётся API и
 * рендерится фронтом через единый резолвер `renderIcon(name)`
 * (EntityDialog.tsx: `CUSTOM_ICONS[name] || LUCIDE[name]`).
 *
 * Тест ловит разъезд контура:
 *  1. backend-имя не резолвится во фронте → иконка не отрисуется;
 *  2. имя в пикере ICON_LIST не резолвится → сломанный выбор;
 *  3. backend-имя отсутствует в пикере → иконку нельзя выбрать в UI
 *     и она потеряется при сохранении через диалог.
 */
import { describe, expect, it } from "vitest"
import * as L from "lucide-react"
import EntityDialogSource from "./EntityDialog.tsx?raw"

const CUSTOM_ICON_NAMES = ["LetterO", "LetterSh"]

// Содержимое всех backend .py файлов (через Vite raw-импорт — без fs/node).
// Пути раскрываются по glob-паттерну относительно этого файла.
const backendRaw = import.meta.glob(
  "../../../../backend/app/**/*.py",
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>

function backendIconNames(): Set<string> {
  const re =
    /"(?:icon|op_icon|section_icon|spg_icon)"\s*:\s*"([A-Za-z][A-Za-z0-9]*)"/g
  const out = new Set<string>()
  for (const text of Object.values(backendRaw)) {
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) out.add(m[1])
  }
  return out
}

function pickerIconNames(): Set<string> {
  const listMatch = EntityDialogSource.match(/const ICON_LIST = \[([\s\S]*?)\]/)
  if (!listMatch) throw new Error("ICON_LIST not found in EntityDialog.tsx")
  return new Set(
    [...listMatch[1].matchAll(/"([A-Za-z]+)"/g)].map((m) => m[1]),
  )
}

const lucide = L as unknown as Record<string, unknown>
const resolves = (name: string) => Boolean(lucide[name] || CUSTOM_ICON_NAMES.includes(name))

describe("сквозной контур иконок (backend → renderIcon → lucide-react)", () => {
  const backend = backendIconNames()
  const picker = pickerIconNames()

  it("все backend-имена резолвятся во фронте", () => {
    const missing = [...backend].filter((n) => !resolves(n))
    expect(missing, "backend-иконки без резолва во фронте").toEqual([])
  })

  it("все имена пикера ICON_LIST резолвятся", () => {
    const missing = [...picker].filter((n) => !resolves(n))
    expect(missing, "иконки пикера без резолва").toEqual([])
  })

  it("пикер покрывает все backend-имена (нет потерянных при сохранении)", () => {
    const notOffered = [...backend].filter((n) => !picker.has(n))
    expect(
      notOffered,
      "backend-иконки, отсутствующие в ICON_LIST — их нельзя выбрать в UI",
    ).toEqual([])
  })
})

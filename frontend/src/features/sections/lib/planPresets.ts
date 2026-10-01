/**
 * lib/planPresets.ts
 * ==================
 * Пресеты настроек печати плана для участка.
 *
 * Хранятся в localStorage по ключу `plan-presets-{sectionId}`.
 * Каждый пресет — это снимок `PrintSettings` (columns, title),
 * который можно применить одним кликом.
 *
 * Первый в списке — базовый пресет участка (`sectionBasePreset`): его колонки
 * задаёт профиль печати участка (`PRINT_PROFILES` по коду секции), поэтому
 * печать плана различается по участкам и открывается уже на своём наборе.
 * Встроенные пресеты помечены `isBuiltin: true` и не сохраняются в
 * localStorage — они всегда доступны.
 */

import {
  COMPACT_PRINT_COLUMNS,
  DEFAULT_PRINT_COLUMNS,
  isPlanColumnKey,
  printColumnsFor,
  type PlanColumnKey,
  type PrintSettings,
} from "./planPrintSettings";

// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

export type PresetId = string;

export interface PlanPreset {
  id: PresetId;
  name: string;
  settings: PrintSettings;
  isBuiltin: boolean;
}

// ---------------------------------------------------------------------------
// Встроенные пресеты — не редактируются, не удаляются
const ALL_COLS: PlanColumnKey[] = [...DEFAULT_PRINT_COLUMNS];
/**
 * «Только артикулы» — короткий лист мастера: артикул и остаток. Без остатка
 * строка не отвечает на вопрос, сколько ещё делать, и артикул в ней не с чем
 * сверить.
 */
const SKU_ONLY: PlanColumnKey[] = ["sku", "balance"];

/**
 * Идентификатор базового пресета участка: он один на все участки, а набор
 * внутри — профиль печати этого участка.
 */
export const SECTION_BASE_PRESET_ID = "builtin-section";

/**
 * Набор пресета, приведённый к колонкам, которые у участка есть: колонка,
 * которой у участка не бывает (упаковка без упаковочных операций, ADR-0059),
 * не должна ни печататься пустой, ни удерживать пресет «неактивным».
 */
function narrowToSection(
  preset: PlanPreset,
  unavailableColumns: readonly PlanColumnKey[],
): PlanPreset {
  return {
    ...preset,
    settings: {
      ...preset.settings,
      columns: preset.settings.columns.filter((key) => !unavailableColumns.includes(key)),
    },
  };
}

/**
 * Базовый пресет участка: печать плана под конкретный участок из
 * `PRINT_PROFILES` (`printColumnsFor`). Стоит первым в списке и открывается
 * активным: настройки окна берут колонки из того же `printColumnsFor`, поэтому
 * базовый набор и «что открылось» — один и тот же набор, а не два похожих.
 *
 * `unavailableColumns` — колонки, которых у участка не бывает (упаковка без
 * упаковочных операций, ADR-0059): набор приводится к применимым, иначе пресет
 * «Базовый» открывался бы неактивным на своём же участке.
 */
export function sectionBasePreset(
  sectionCode?: string | null,
  unavailableColumns: readonly PlanColumnKey[] = [],
): PlanPreset {
  return narrowToSection(
    {
      id: SECTION_BASE_PRESET_ID,
      name: "Базовый",
      settings: { columns: printColumnsFor(sectionCode), title: "" },
      isBuiltin: true,
    },
    unavailableColumns,
  );
}

export const BUILTIN_PRESETS: PlanPreset[] = [
  {
    id: "builtin-full",
    name: "Полный план",
    settings: { columns: ALL_COLS, title: "" },
    isBuiltin: true,
  },
  {
    id: "builtin-sku-plan",
    name: "Только артикулы",
    settings: { columns: SKU_ONLY, title: "" },
    isBuiltin: true,
  },
  {
    id: "builtin-compact",
    name: "Компактный",
    settings: { columns: [...COMPACT_PRINT_COLUMNS], title: "" },
    isBuiltin: true,
  },
];

// ---------------------------------------------------------------------------
// Загрузка / сохранение кастомных пресетов
// ---------------------------------------------------------------------------

function storageKey(sectionId: number): string {
  return `plan-presets-${sectionId}`;
}

/** Старые сохранённые пресеты могли содержать неизвестные ключи колонок. */
function normalizeSettings(settings: PrintSettings): PrintSettings {
  return {
    ...settings,
    columns: settings.columns.filter(isPlanColumnKey),
  };
}

function loadCustomPresets(sectionId: number): PlanPreset[] {
  try {
    const raw = localStorage.getItem(storageKey(sectionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (p): p is PlanPreset =>
          typeof p === "object" &&
          p !== null &&
          typeof (p as PlanPreset).id === "string" &&
          typeof (p as PlanPreset).name === "string" &&
          typeof (p as PlanPreset).settings === "object",
      )
      .map((p) => ({
        ...p,
        settings: normalizeSettings(p.settings),
        isBuiltin: false,
      }));
  } catch {
    return [];
  }
}

function saveCustomPresets(sectionId: number, presets: PlanPreset[]): void {
  try {
    localStorage.setItem(storageKey(sectionId), JSON.stringify(presets));
  } catch {}
}

/** Пресеты участка: первым — базовый набор этого участка, все — по применимым колонкам. */
export function loadPresets(
  sectionId: number,
  sectionCode?: string | null,
  unavailableColumns: readonly PlanColumnKey[] = [],
): PlanPreset[] {
  const presets = [
    sectionBasePreset(sectionCode),
    ...BUILTIN_PRESETS,
    ...loadCustomPresets(sectionId),
  ];
  if (unavailableColumns.length === 0) return presets;
  return presets.map((preset) => narrowToSection(preset, unavailableColumns));
}

export function addPreset(
  sectionId: number,
  name: string,
  settings: PrintSettings,
): PlanPreset {
  const custom = loadCustomPresets(sectionId);
  const preset: PlanPreset = {
    id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: name.trim() || "Без названия",
    settings: { ...settings },
    isBuiltin: false,
  };
  custom.push(preset);
  saveCustomPresets(sectionId, custom);
  return preset;
}

export function deletePreset(sectionId: number, presetId: PresetId): void {
  const custom = loadCustomPresets(sectionId).filter((p) => p.id !== presetId);
  saveCustomPresets(sectionId, custom);
}

// ---------------------------------------------------------------------------
// Утилиты сравнения
// ---------------------------------------------------------------------------

export function isSameSettings(a: PrintSettings, b: PrintSettings): boolean {
  if (a.title !== b.title) return false;
  if (a.columns.length !== b.columns.length) return false;
  const aCols = new Set(a.columns);
  return b.columns.every((c) => aCols.has(c));
}

export function findMatchingPresetId(
  presets: PlanPreset[],
  settings: PrintSettings,
): PresetId | null {
  for (const p of presets) {
    if (isSameSettings(p.settings, settings)) return p.id;
  }
  return null;
}

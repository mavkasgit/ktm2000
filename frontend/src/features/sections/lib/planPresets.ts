/**
 * lib/planPresets.ts
 * ==================
 * Пресеты настроек печати плана для участка.
 *
 * Хранятся в localStorage по ключу `plan-presets-{sectionId}`.
 * Каждый пресет — это снимок `PrintSettings` (columns, title),
 * который можно применить одним кликом.
 *
 * Встроенные пресеты (BUILTIN_PRESETS) помечены `isBuiltin: true` и
 * не сохраняются в localStorage — они всегда доступны.
 */

import {
  COMPACT_PRINT_COLUMNS,
  DEFAULT_PRINT_COLUMNS,
  isPlanColumnKey,
  PRINT_PROFILES,
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
const SKU_ONLY: PlanColumnKey[] = ["sku"];

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
  {
    id: "builtin-hangers",
    name: "С подвесами",
    settings: {
      columns: [...(PRINT_PROFILES.ANODIZING ?? DEFAULT_PRINT_COLUMNS)],
      title: "",
    },
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

export function loadPresets(sectionId: number): PlanPreset[] {
  return [...BUILTIN_PRESETS, ...loadCustomPresets(sectionId)];
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

import { beforeEach, describe, expect, it } from "vitest";

import {
  addPreset,
  findMatchingPresetId,
  loadPresets,
  SECTION_BASE_PRESET_ID,
} from "./planPresets";
import {
  PACKAGING_ONLY_COLUMNS,
  PRINT_PROFILES,
  printColumnsFor,
  type PlanColumnKey,
} from "./planPrintSettings";

describe("базовый пресет участка", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("идёт первым и несёт профиль печати своего участка", () => {
    const sawing = loadPresets(1, "SAWING")[0];
    const packing = loadPresets(1, "PACKING")[0];

    expect(sawing?.id).toBe(SECTION_BASE_PRESET_ID);
    expect(sawing?.isBuiltin).toBe(true);
    expect(sawing?.settings.columns).toEqual(printColumnsFor("SAWING"));
    expect(packing?.settings.columns).toEqual(printColumnsFor("PACKING"));
    expect(packing?.settings.columns).not.toEqual(sawing?.settings.columns);
  });

  it("открывается активным: набор окна и базовый набор — один и тот же", () => {
    const presets = loadPresets(1, "ANODIZING");

    const active = findMatchingPresetId(presets, {
      columns: printColumnsFor("ANODIZING"),
      title: "",
    });

    expect(active).toBe(SECTION_BASE_PRESET_ID);
  });

  it("на участке без упаковочных операций «Упаковки» в базовом наборе нет", () => {
    const presets = loadPresets(1, "ANODIZING", PACKAGING_ONLY_COLUMNS);
    const base = presets[0];
    const expected = printColumnsFor("ANODIZING").filter(
      (key: PlanColumnKey) => !PACKAGING_ONLY_COLUMNS.includes(key),
    );

    expect(base?.settings.columns).toEqual(expected);
    // Тем же набором открывается окно: иначе базовый пресет был бы неактивен.
    expect(findMatchingPresetId(presets, { columns: expected, title: "" })).toBe(
      SECTION_BASE_PRESET_ID,
    );
  });

  it("неизвестный код участка — общий профиль", () => {
    expect(loadPresets(1, "NO_SUCH_SECTION")[0]?.settings.columns).toEqual(PRINT_PROFILES["*"]);
    expect(loadPresets(1, null)[0]?.settings.columns).toEqual(PRINT_PROFILES["*"]);
  });

  it("пользовательские пресеты идут после встроенных, идентификаторы не повторяются", () => {
    const custom = addPreset(1, "Смена", { columns: ["sku"], title: "Смена" });
    const presets = loadPresets(1, "SAWING");
    const ids = presets.map((preset) => preset.id);

    expect(ids[0]).toBe(SECTION_BASE_PRESET_ID);
    expect(ids[ids.length - 1]).toBe(custom.id);
    expect(ids).toContain("builtin-full");
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("у каждого участка из PRINT_PROFILES базовый набор — его профиль", () => {
    for (const [sectionCode, columns] of Object.entries(PRINT_PROFILES)) {
      expect(loadPresets(1, sectionCode)[0]?.settings.columns).toEqual(columns);
    }
  });
});

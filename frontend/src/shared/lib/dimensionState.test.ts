import { describe, expect, it } from "vitest";

import {
  DIMENSION_FIELDS,
  DIMENSION_STATES,
  DIMENSION_STATE_LABELS,
  dimensionFieldCodes,
  isLengthState,
} from "./dimensionState";

describe("isLengthState", () => {
  it("length — истина", () => {
    expect(isLengthState("length")).toBe(true);
    expect(isLengthState(null)).toBe(true);
    expect(isLengthState(undefined)).toBe(true);
  });

  it("area/volume — ложь", () => {
    expect(isLengthState("area")).toBe(false);
    expect(isLengthState("volume")).toBe(false);
  });
});

describe("DIMENSION_STATES/LABELS", () => {
  it("полный набор в доменном порядке", () => {
    expect(DIMENSION_STATES).toEqual(["length", "area", "volume"]);
    expect(DIMENSION_STATE_LABELS.length).toBe("Длина");
    expect(DIMENSION_STATE_LABELS.area).toBe("2D");
    expect(DIMENSION_STATE_LABELS.volume).toBe("3D");
  });
});

describe("DIMENSION_FIELDS", () => {
  it("2D — длина × ширина × толщина", () => {
    expect(DIMENSION_FIELDS.area.map((f) => f.code)).toEqual([
      "length_mm",
      "width_mm",
      "thickness_mm",
    ]);
  });

  it("3D — длина × ширина × высота", () => {
    expect(DIMENSION_FIELDS.volume.map((f) => f.code)).toEqual([
      "length_mm",
      "width_mm",
      "height_mm",
    ]);
  });

  it("dimensionFieldCodes: length → null, area/volume → коды", () => {
    expect(dimensionFieldCodes("length")).toBeNull();
    expect(dimensionFieldCodes("area")).toEqual(["length_mm", "width_mm", "thickness_mm"]);
    expect(dimensionFieldCodes("volume")).toEqual(["length_mm", "width_mm", "height_mm"]);
  });
});

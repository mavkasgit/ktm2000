import { describe, expect, it } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { getPairedHangerLabel, getQtyPerHanger } from "./PlanHangerDisplay";

function taskWithPayload(sourcePayload: Record<string, unknown>): SectionBoardTask {
  return { source_payload: sourcePayload } as SectionBoardTask;
}

describe("getQtyPerHanger / getPairedHangerLabel — парные профили (#171)", () => {
  it("снапшот product_pair: N из снапшота, метка парная", () => {
    const task = taskWithPayload({
      product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
    });

    expect(getQtyPerHanger(task)).toBe(8);
    expect(getPairedHangerLabel(task)).toBe("8");
  });

  it("override позиции поверх снапшота побеждает", () => {
    const task = taskWithPayload({
      product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
      quantity_per_hanger: 5,
    });

    expect(getQtyPerHanger(task)).toBe(5);
    expect(getPairedHangerLabel(task)).toBe("5");
  });

  it("не парный payload: обычное значение, парной метки нет", () => {
    const task = taskWithPayload({ quantity_per_hanger: 5 });

    expect(getQtyPerHanger(task)).toBe(5);
    expect(getPairedHangerLabel(task)).toBeNull();
  });

  it("пустой payload — значения и метки нет", () => {
    const task = taskWithPayload({});

    expect(getQtyPerHanger(task)).toBeNull();
    expect(getPairedHangerLabel(task)).toBeNull();
  });

  it("нерезолвленный снапшот пары не отдаёт N", () => {
    const task = taskWithPayload({
      product_pair: { resolved: false, quantity_per_hanger: 8 },
    });

    expect(getQtyPerHanger(task)).toBeNull();
    expect(getPairedHangerLabel(task)).toBeNull();
  });

  it("неположительный override не считается override — берётся снапшот", () => {
    for (const override of [0, -3]) {
      const task = taskWithPayload({
        product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
        quantity_per_hanger: override,
      });

      expect(getQtyPerHanger(task)).toBe(8);
      expect(getPairedHangerLabel(task)).toBe("8");
    }
  });

  it("одиночная позиция: неположительный override не отдаётся", () => {
    for (const override of [0, -3]) {
      const task = taskWithPayload({ quantity_per_hanger: override });

      expect(getQtyPerHanger(task)).toBeNull();
      expect(getPairedHangerLabel(task)).toBeNull();
    }
  });
});

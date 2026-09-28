import { describe, expect, it } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { getQtyPerHanger } from "./PlanHangerDisplay";

function taskWithPayload(sourcePayload: Record<string, unknown>): SectionBoardTask {
  return { source_payload: sourcePayload } as SectionBoardTask;
}

describe("getQtyPerHanger — парные профили (#171)", () => {
  it("снапшот product_pair: N из снапшота", () => {
    const task = taskWithPayload({
      product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
    });

    expect(getQtyPerHanger(task)).toBe(8);
  });

  it("override позиции поверх снапшота побеждает", () => {
    const task = taskWithPayload({
      product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
      quantity_per_hanger: 5,
    });

    expect(getQtyPerHanger(task)).toBe(5);
  });

  it("не парный payload: обычное значение", () => {
    const task = taskWithPayload({ quantity_per_hanger: 5 });

    expect(getQtyPerHanger(task)).toBe(5);
  });

  it("пустой payload — значения нет", () => {
    expect(getQtyPerHanger(taskWithPayload({}))).toBeNull();
  });

  it("нерезолвленный снапшот пары не отдаёт N", () => {
    const task = taskWithPayload({
      product_pair: { resolved: false, quantity_per_hanger: 8 },
    });

    expect(getQtyPerHanger(task)).toBeNull();
  });

  it("неположительный override не считается override — берётся снапшот", () => {
    for (const override of [0, -3]) {
      const task = taskWithPayload({
        product_pair: { resolved: true, quantity_per_hanger: 8, source: "manual" },
        quantity_per_hanger: override,
      });

      expect(getQtyPerHanger(task)).toBe(8);
    }
  });

  it("одиночная позиция: неположительный override не отдаётся", () => {
    for (const override of [0, -3]) {
      const task = taskWithPayload({ quantity_per_hanger: override });

      expect(getQtyPerHanger(task)).toBeNull();
    }
  });

  it("дробная норма не округляется (#201)", () => {
    const task = taskWithPayload({
      product_pair: { resolved: true, quantity_per_hanger: 2.5, source: "manual" },
    });

    expect(getQtyPerHanger(task)).toBe(2.5);
  });
});

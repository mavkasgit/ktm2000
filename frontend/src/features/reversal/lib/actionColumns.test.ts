import { describe, expect, it } from "vitest";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import {
  actionColumns,
  actionTypeLabel,
  getActionTone,
  statusLabel,
  type ActionFilterField,
} from "./actionColumns";

describe("actionColumns", () => {
  it("объявляет фильтр только там, где сервер его понимает", () => {
    const filterable = actionColumns
      .filter((column) => column.filterField)
      .map((column) => [column.id, column.apiParam]);

    expect(filterable).toEqual([
      ["actionType", "action_type"],
      ["status", "status"],
    ]);
  });

  it("не объявляет сортировку ни у одной колонки: сервер отдаёт id.desc()", () => {
    expect(actionColumns.some((column) => column.sortField)).toBe(false);
  });

  it("собирает параметры запроса из описания, а не перечислением", () => {
    const params = buildColumnApiParams<ActionFilterField>(
      { actionType: new Set(["transfer_send"]), status: new Set(["active"]) },
      {},
      actionColumns,
    );

    expect(params).toEqual({ action_type: "transfer_send", status: "active" });
  });

  it("подпись статуса и типа не теряется, а неизвестное значение показывается как есть", () => {
    expect(statusLabel("active")).toBe("Активно");
    expect(statusLabel("archived")).toBe("archived");
    expect(actionTypeLabel("transfer_send")).toBe("Передача отправлена");
    expect(actionTypeLabel("quality_recheck")).toBe("quality_recheck");
  });

  it("тон строки отвечает на «можно ли ещё что-то сделать», а не на цвет бейджа", () => {
    expect(getActionTone("active")).toBe("active");
    expect(getActionTone("amended")).toBe("activeRunning");
    expect(getActionTone("reversed")).toBe("completed");
    expect(getActionTone("purged")).toBe("waiting");
    // Новый статус в бэке не должен красить строку наугад.
    expect(getActionTone("archived")).toBe("plain");
  });
});

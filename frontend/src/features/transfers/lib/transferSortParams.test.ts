import { describe, expect, it } from "vitest";

import {
  buildHistorySortParam,
  buildReadySortParam,
  mapHistorySortFieldToApi,
  mapReadySortFieldToApi,
} from "./transferSortParams";

describe("маппер колонок «Готово к передаче»", () => {
  it("каждая колонка уходит под своим полем ORDER BY бэкенда", () => {
    expect(mapReadySortFieldToApi("positionId")).toBe("plan_position_id");
    expect(mapReadySortFieldToApi("sku")).toBe("product_sku");
    expect(mapReadySortFieldToApi("dimensions")).toBe("dimensions");
    expect(mapReadySortFieldToApi("stage")).toBe("operation_name");
    expect(mapReadySortFieldToApi("transferableQty")).toBe("transferable_qty");
    expect(mapReadySortFieldToApi("next")).toBe("next_section_name");
  });
});

describe("маппер колонок журнала передач", () => {
  it("имена полей журнала — псевдонимы контракта API, не имена колонок", () => {
    expect(mapHistorySortFieldToApi("from")).toBe("from");
    expect(mapHistorySortFieldToApi("to")).toBe("to");
    expect(mapHistorySortFieldToApi("sku")).toBe("sku");
    expect(mapHistorySortFieldToApi("quantity")).toBe("quantity");
    expect(mapHistorySortFieldToApi("status")).toBe("status");
  });
});

describe("сборка строки sort", () => {
  it("без выбранных колонок уходит дефолт эндпоинта", () => {
    // «Готово к передаче» открывается крупными партиями: пока колонка не
    // выбрана, страница показывает свёрнутые группы, и порядок строк задаёт
    // сервер.
    expect(buildReadySortParam([])).toBe("transferable_qty:desc");
    expect(buildHistorySortParam([])).toBe("created_at:desc");
  });

  it("все выбранные приоритеты уходят в порядке выбора, а не только первый", () => {
    const ready = buildReadySortParam([
      { field: "positionId", order: "desc" },
      { field: "transferableQty", order: "desc" },
    ]);
    expect(ready).toBe("plan_position_id:desc,transferable_qty:desc");
  });

  it("журнал собирает несколько приоритетов в одну строку", () => {
    const history = buildHistorySortParam([
      { field: "status", order: "asc" },
      { field: "quantity", order: "desc" },
    ]);
    expect(history).toBe("status:asc,quantity:desc");
  });
});

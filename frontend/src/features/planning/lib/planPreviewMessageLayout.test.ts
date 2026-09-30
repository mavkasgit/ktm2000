import { describe, expect, it } from "vitest";

import { planPreviewMessageLayout, PLAN_PREVIEW_TOTAL_COLUMNS } from "./planPreviewMessageLayout";

// Сумма colSpan всех ячеек строки должна равняться числу колонок таблицы —
// иначе строка с сырыми данными (или уголок сброса) уезжает за сетку.
const ROW_SPANS = 10;

describe("planPreviewMessageLayout", () => {
  it("только ошибки: ошибки занимают обе колонки пары, маршрут — свою", () => {
    const layout = planPreviewMessageLayout(true, false);

    expect(layout.errorsColSpan).toBe(2);
    expect(layout.warningsColSpan).toBe(0);
    expect(layout.routeColSpan).toBe(1);
  });

  it("только предупреждения: предупреждения занимают обе колонки пары", () => {
    const layout = planPreviewMessageLayout(false, true);

    expect(layout.errorsColSpan).toBe(0);
    expect(layout.warningsColSpan).toBe(2);
    expect(layout.routeColSpan).toBe(1);
  });

  it("оба типа: каждое сообщение в своей колонке", () => {
    const layout = planPreviewMessageLayout(true, true);

    expect(layout.errorsColSpan).toBe(1);
    expect(layout.warningsColSpan).toBe(1);
    expect(layout.routeColSpan).toBe(1);
  });

  it("без сообщений: маршрут забирает все три слота", () => {
    const layout = planPreviewMessageLayout(false, false);

    expect(layout.errorsColSpan).toBe(0);
    expect(layout.warningsColSpan).toBe(0);
    expect(layout.routeColSpan).toBe(3);
  });

  it("развёрнутая строка закрывает всю таблицу при любом наборе сообщений", () => {
    for (const hasErrors of [true, false]) {
      for (const hasWarnings of [true, false]) {
        const layout = planPreviewMessageLayout(hasErrors, hasWarnings);
        const label = `errors=${hasErrors}, warnings=${hasWarnings}`;

        // 6 колонок до маршрута + слоты сообщений + уголок сброса.
        const rowSpan =
          6 + layout.routeColSpan + layout.errorsColSpan + layout.warningsColSpan + 1;
        expect(rowSpan, label).toBe(ROW_SPANS);
        expect(layout.detailColSpan, label).toBe(PLAN_PREVIEW_TOTAL_COLUMNS);
      }
    }
  });
});

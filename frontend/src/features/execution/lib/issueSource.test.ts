import { describe, expect, it } from "vitest";

import type {
  IssuePreviewCandidate,
  IssuePreviewHint,
  IssuePreviewOut,
} from "@/shared/api/productionPlans";
import { QTY_EMPTY } from "@/shared/lib/quantityFormat";

import {
  ISSUE_DEFAULT_STRATEGY,
  buildAutoIssueSelection,
  buildIssueCandidateGroups,
  buildIssueSelection,
  groupBalanceIds,
  groupRemainingAfter,
  isCandidateChecked,
  isGroupChecked,
  isGroupIndeterminate,
  issueCollectLine,
  issueConfirmBlockReason,
  remainingAfterCell,
  toggleBalanceExcluded,
  toggleGroupExcluded,
  visibleIssueHints,
} from "./issueSource";

const candidate = (over: Partial<IssuePreviewCandidate>): IssuePreviewCandidate => ({
  balance_id: 1,
  location_id: 1,
  location_name: "Склад",
  group_key: 0,
  product_id: 0,
  sku: null,
  dimensions: null,
  completed_operations: [],
  ops_count: 0,
  available: "10",
  take: "10",
  remaining_after: "0",
  included: true,
  target_sequence: 3,
  order: 0,
  ...over,
});

const hint = (over: Partial<IssuePreviewHint>): IssuePreviewHint => ({
  kind: "defect",
  location_id: 1,
  location_name: "Склад",
  quantity: "5",
  text: "На складе есть брак 5 шт.",
  ...over,
});

describe("issueSource: «останется после» — прочерк против нуля (#282)", () => {
  it("`null` → прочерк со смыслом «не доходила очередь», а не ноль", () => {
    const cell = remainingAfterCell(null);
    expect(cell.text).toBe(QTY_EMPTY);
    expect(cell.notReached).toBe(true);
    expect(cell.drawnOut).toBe(false);
  });

  it('`"0"` → ноль с пометкой «вычерпан целиком», это НЕ прочерк', () => {
    const cell = remainingAfterCell("0");
    expect(cell.text).toBe("0");
    expect(cell.drawnOut).toBe(true);
    expect(cell.notReached).toBe(false);
    // Различие обязательное: пустеющий склад и склад, до которого очередь не
    // дошла, — разные решения оператора, и печать у них не должна совпадать.
    expect(cell.text).not.toBe(remainingAfterCell(null).text);
  });

  it("нецелевое значение печатается живой дробью без пометок", () => {
    const cell = remainingAfterCell("12.5");
    expect(cell.text).toBe("12,5");
    expect(cell.drawnOut).toBe(false);
    expect(cell.notReached).toBe(false);
  });
});

describe("issueSource: галочка склада живёт ровно этот вызов", () => {
  it("снятие галочки добавляет balance_id в excluded, возврат — убирает", () => {
    const excluded = toggleBalanceExcluded([], 7, false);
    expect(excluded).toEqual([7]);
    expect(toggleBalanceExcluded(excluded, 7, true)).toEqual([]);
    // Другой склад не затирает уже снятый.
    expect(toggleBalanceExcluded([7], 9, false)).toEqual([7, 9]);
  });

  it("галочка строки честна к списку снятых", () => {
    expect(isCandidateChecked(candidate({ balance_id: 7 }), [])).toBe(true);
    expect(isCandidateChecked(candidate({ balance_id: 7 }), [7])).toBe(false);
  });
});

describe("issueSource: подсказки только по включённым складам", () => {
  it("по складу со снятой галочкой (`included: false`) подсказка не показывается", () => {
    const candidates = [
      candidate({ balance_id: 1, location_id: 1, included: true }),
      candidate({ balance_id: 2, location_id: 2, included: false }),
    ];
    const hints = [
      hint({ location_id: 1, location_name: "Склад 1" }),
      hint({ location_id: 2, location_name: "Склад 2", text: "Брак на снятом складе" }),
    ];

    const visible = visibleIssueHints(hints, candidates);
    expect(visible).toHaveLength(1);
    expect(visible[0].location_id).toBe(1);
    expect(visible.some((h) => h.location_id === 2)).toBe(false);
  });
});

describe("issueSource: строка группы эквивалентов на осях склада", () => {
  it("складывает серверные available/take, а строки ставит по минимальному order", () => {
    const groups = buildIssueCandidateGroups(
      [
        candidate({
          balance_id: 1,
          location_id: 10,
          location_name: "Склад",
          group_key: 5,
          product_id: 100,
          sku: "A",
          available: "10",
          take: "10",
          remaining_after: "0",
          order: 3,
        }),
        candidate({
          balance_id: 2,
          location_id: 10,
          location_name: "Склад",
          group_key: 5,
          product_id: 200,
          sku: "B",
          available: "5",
          take: "5",
          remaining_after: "2",
          order: 0,
        }),
        candidate({
          balance_id: 3,
          location_id: 20,
          location_name: "Другой",
          group_key: 5,
          product_id: 100,
          sku: "A",
          available: "7",
          take: "0",
          remaining_after: null,
          order: 1,
        }),
      ],
      100,
    );

    // Строка — (group_key, location, dimensions, operations), не один group_key:
    // остатки группы на разных складах — разные строки выдачи.
    expect(groups.map((group) => group.locationId)).toEqual([10, 20]);
    expect(groups[0].available).toBe("15");
    expect(groups[0].take).toBe("15");
    // Внутри строки кандидаты идут по `order`, а не по порядку массива.
    expect(groups[0].candidates.map((row) => row.order)).toEqual([0, 3]);
    expect(groups[0].balanceIds).toEqual([2, 1]);
    expect(groups[0].skuLabel).toBe("A, B (эквиваленты)");
    expect(groups[0].hasTaskProduct).toBe(true);
    expect(groups[1].skuLabel).toBe("A");
  });

  it("разные размеры и операции одной группы — разные строки", () => {
    const groups = buildIssueCandidateGroups(
      [
        candidate({
          balance_id: 1,
          location_id: 10,
          group_key: 5,
          product_id: 100,
          sku: "A",
          dimensions: { length_mm: 1000 },
          completed_operations: ["CUT"],
          order: 0,
        }),
        candidate({
          balance_id: 2,
          location_id: 10,
          group_key: 5,
          product_id: 200,
          sku: "B",
          dimensions: { length_mm: 2000 },
          completed_operations: ["CUT"],
          order: 1,
        }),
        candidate({
          balance_id: 3,
          location_id: 10,
          group_key: 5,
          product_id: 100,
          sku: "A",
          dimensions: { length_mm: 1000 },
          completed_operations: ["CUT", "PAINT"],
          order: 2,
        }),
      ],
      100,
    );

    expect(groups).toHaveLength(3);
  });

  it("remaining_after группы: все null → null, иначе сумма только не-null значений", () => {
    expect(
      groupRemainingAfter([
        candidate({ remaining_after: null }),
        candidate({ remaining_after: null }),
      ]),
    ).toBeNull();
    expect(
      groupRemainingAfter([
        candidate({ remaining_after: null }),
        candidate({ remaining_after: "2,5" }),
      ]),
    ).toBe("2,5");
    expect(
      groupRemainingAfter([
        candidate({ remaining_after: "0" }),
        candidate({ remaining_after: "2" }),
      ]),
    ).toBe("2");
  });
});

describe("issueSource: галочка группы эквивалентов", () => {
  it("группа снята, только когда сняты ВСЕ её balance_id; часть — indeterminate", () => {
    const ids = groupBalanceIds([
      candidate({ balance_id: 1 }),
      candidate({ balance_id: 2 }),
    ]);
    expect(ids).toEqual([1, 2]);
    expect(isGroupChecked(ids, [])).toBe(true);
    expect(isGroupIndeterminate(ids, [])).toBe(false);
    expect(isGroupChecked(ids, [1])).toBe(true);
    expect(isGroupIndeterminate(ids, [1])).toBe(true);
    expect(isGroupChecked(ids, [1, 2])).toBe(false);
    expect(isGroupIndeterminate(ids, [1, 2])).toBe(false);
  });

  it("toggleGroupExcluded включает/выключает все balance_id строки без дублей", () => {
    const ids = [1, 2, 3];
    expect(toggleGroupExcluded([], ids, false)).toEqual([1, 2, 3]);
    expect(toggleGroupExcluded([1, 2, 3, 9], ids, true)).toEqual([9]);
    expect(toggleGroupExcluded([1], ids, false)).toEqual([1, 2, 3]);
  });
});

describe("issueSource: итог «собрано X из Y, дефицит Z»", () => {
  it("одна строка для предпросмотра и итога, количество — серверный формат", () => {
    expect(
      issueCollectLine({ required: "40", collected: "2,5", deficit: "37,5" }),
    ).toBe("Собрано 2,5 из 40 шт., дефицит 37,5 шт.");
  });
});

describe("issueSource: кнопка подтверждается только когда выдача возможна", () => {
  const preview = (over: Partial<IssuePreviewOut>): IssuePreviewOut => ({
    position_id: 1,
    product_id: 1,
    group_key: 1,
    group_skus: ["SKU-1"],
    required: "10",
    required_dimensions: null,
    required_dimensions_label: null,
    collected: "10",
    deficit: "0",
    candidates: [candidate({})],
    hints: [],
    ...over,
  });

  it("текст серверного отказа показывается как есть, своей формулировки нет", () => {
    const reason = issueConfirmBlockReason({
      preview: null,
      isLoading: false,
      errorText: "Недостаточно остатка для стратегии «отказ»",
    });
    expect(reason).toBe("Недостаточно остатка для стратегии «отказ»");
  });

  it("пустой список кандидатов — причина «выдавать нечего»", () => {
    const reason = issueConfirmBlockReason({
      preview: preview({ candidates: [], collected: "0" }),
      isLoading: false,
      errorText: null,
    });
    expect(reason).toMatch(/выдавать нечего/);
    // Текст серверный (#395): отказ говорит про группу эквивалентов, а не
    // про один артикул задания.
    expect(reason).toContain("материала группы эквивалентов в нужном размере");
  });

  it("собрано 0 при непустых кандидатах — тоже блокировка", () => {
    const reason = issueConfirmBlockReason({
      preview: preview({ collected: "0" }),
      isLoading: false,
      errorText: null,
    });
    expect(reason).toBe("Собрано 0 шт. — выдавать нечего");
  });

  it("посчитанный подбор без ошибок — причина снята (кнопка активна)", () => {
    expect(
      issueConfirmBlockReason({ preview: preview({}), isLoading: false, errorText: null }),
    ).toBeNull();
  });
});

describe("issueSource: групповой запуск умеет только auto без галочек", () => {
  it("`buildAutoIssueSelection` → `auto: true` без `excluded_balance_ids`", () => {
    const selection = buildAutoIssueSelection("bulk-1");
    expect(selection.auto).toBe(true);
    // Галочки принадлежат конкретной позиции: в групповом payload их нет вовсе.
    expect("excluded_balance_ids" in selection).toBe(false);
    expect(selection.idempotency_key).toBe("bulk-1");
  });

  it("ручной выбор одной позиции несёт снятые галочки и стратегию", () => {
    const selection = buildIssueSelection({
      excludedBalanceIds: [7, 9],
      strategy: "fail",
      idempotencyKey: "manual-1",
    });
    expect(selection).toEqual({
      excluded_balance_ids: [7, 9],
      shortage_strategy: "fail",
      auto: false,
      idempotency_key: "manual-1",
    });
  });

  it("стратегия по умолчанию — серверный `partial`", () => {
    expect(ISSUE_DEFAULT_STRATEGY).toBe("partial");
  });
});

/**
 * Массовый ввод факта на доске: раскладка, потолки и пачка записей (#283).
 *
 * Контракт, который защищают тесты: введённое в поле группы раскладывается
 * последовательно сверху вниз, потолок строки — доступное на задачу, избыток
 * не теряется и остаётся в последней строке; пустое поле — отсутствие ввода
 * (не ноль); в пачку уходят только заполненные и доводимые задания, а
 * недоводимые возвращаются отдельным списком, чтобы футер сказал о них
 * оператору.
 */

import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";

import {
  applyGroupField,
  draftEntries,
  draftEntryTotals,
  draftQtyFor,
  draftShortage,
  draftEntryFieldSummary,
  draftTotals,
  groupDraftValue,
  groupRecordedFact,
  resolveGroupFact,
  type DraftEntryField,
  EMPTY_DRAFT_QTY,
  distributeSequential,
  isDraftEmpty,
  taskFactCeiling,
  withDraftField,
  withoutDraftIds,
} from "./bulkDraft";

/** Запись по колонке в тестах: порция при записанном факте 0. */
function entryField(quantity: number, mode: "add" | "set" = "add"): DraftEntryField {
  return { quantity, mode, recorded: 0, target: quantity };
}

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    is_significant: true,
    planned_quantity: "10",
    // Доводимое задание — «в работе»: `ready` без принятой передачи считается
    // «не передано» и в пачку не попадает.
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "10",
    },
    previous_stage: null,
    next_task_id: null,
    next_task_status: null,
    next_operation_name: null,
    source_ref: null,
    source_payload: {},
    source_fingerprint: null,
    input_sku: "SKU-A",
    output_sku: "SKU-A",
    display_sku: "SKU-A",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

describe("bulkDraft: черновик по id задачи", () => {
  it("хранит значения у своих задач и переживает смену набора строк", () => {
    const draft = withDraftField(withDraftField({}, 7, "good", "3"), 9, "defect", "2");

    expect(draftQtyFor(draft, 7)).toEqual({ good: "3", defect: "" });
    expect(draftQtyFor(draft, 9)).toEqual({ good: "", defect: "2" });
    expect(draftQtyFor(draft, 42)).toEqual(EMPTY_DRAFT_QTY);
  });

  it("пустая строка — отсутствие ввода, а не ноль", () => {
    const filled = withDraftField({}, 1, "good", "0");
    expect(draftTotals([makeTask({ id: 1 })], filled).tasks).toBe(1);

    const cleared = withDraftField(filled, 1, "good", "");
    expect(cleared).toEqual({});
    expect(isDraftEmpty(cleared)).toBe(true);
  });

  it("снятие выделения убирает черновик снятых заданий", () => {
    const draft = withDraftField(withDraftField({}, 1, "good", "5"), 2, "good", "7");

    expect(withoutDraftIds(draft, [1])).toEqual({ 2: { good: "7", defect: "" } });
    expect(withoutDraftIds(draft, [5])).toBe(draft);
  });

  it("итоги считают только заполненные задания", () => {
    const draft = withDraftField(withDraftField({}, 1, "good", "5"), 2, "defect", "4");

    const tasks = [makeTask({ id: 1 }), makeTask({ id: 2 })];
    expect(draftTotals(tasks, draft)).toEqual({ good: 5, defect: 4, tasks: 2 });
    expect(draftTotals(tasks, {})).toEqual({ good: 0, defect: 0, tasks: 0 });
  });
});

describe("bulkDraft: потолок строки", () => {
  it("включает в работу и то, что участок может довыдать", () => {
    const task = makeTask({
      cache: {
        available_quantity: "4",
        issued_quantity: "10",
        completed_quantity: "3",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "1",
        remaining_quantity: "10",
      },
    });

    // 10 − 3 − 1 = 6 в работе, плюс 4 к довыдаче.
    expect(taskFactCeiling(task)).toBe(10);
  });

  it("у раскроя потолок — остаток входа и без довыдачи", () => {
    const task = makeTask({
      transforms_dimensions: true,
      input_quantity: "150",
      input_consumed_quantity: "75",
      outputs: [{ row_number: 1, quantity: "50" }],
      cache: {
        available_quantity: "500",
        issued_quantity: "150",
        completed_quantity: "0",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "5",
        remaining_quantity: "150",
      },
    });

    expect(taskFactCeiling(task)).toBe(70);
  });
});

describe("bulkDraft: последовательная раскладка", () => {
  it("заполняет строки сверху вниз до потолка каждой", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "10", available_quantity: "0" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "4", available_quantity: "0" } }),
    ];

    expect(distributeSequential(tasks, 12)).toEqual([
      { taskId: 1, value: 10, overPlan: false },
      { taskId: 2, value: 2, overPlan: false },
    ]);
  });

  it("избыток не теряет: садится в последнюю строку и помечается", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "10", available_quantity: "0" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "4", available_quantity: "0" } }),
    ];

    expect(distributeSequential(tasks, 18)).toEqual([
      { taskId: 1, value: 10, overPlan: false },
      { taskId: 2, value: 8, overPlan: true },
    ]);
  });

  it("ввод в поле группы виден в строках, очистка возвращает плейсхолдеры", () => {
    const tasks = [makeTask({ id: 1 }), makeTask({ id: 2 })];

    const filled = applyGroupField({}, tasks, "good", "15");
    expect(filled[1]).toEqual({ good: "10", defect: "" });
    expect(filled[2]).toEqual({ good: "5", defect: "" });

    expect(applyGroupField(filled, tasks, "good", "")).toEqual({});
  });

  it("порция, равная нулю, ввода не создаёт: черновик остаётся пустым", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "40" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "20" } }),
    ];
    // Цель равна записанному: записывать нечего, и строки не должны выглядеть
    // заполненными — иначе выход из режима спрашивает подтверждение выхода
    // ради черновика, который ничего не уедет.
    expect(applyGroupField({}, tasks, "good", "60")).toEqual({});
    expect(applyGroupField({}, tasks, "good", "+0")).toEqual({});
  });
});

describe("bulkDraft: записанный факт группы", () => {
  it("плейсхолдер поля и разбор ввода считаются от одной базы", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "2.4" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "0.4" } }),
    ];
    // Дробный остаток от разбора: сумма записанного по строкам — целые штуки
    // (2 + 0), а не «2,8». Плейсхолдер «сейчас 3» отправляет оператора в цель,
    // которую сервер отвергнет как меньшую записанного.
    expect(groupRecordedFact(tasks, "good")).toBe(2);
    expect(resolveGroupFact(tasks, "good", "3").recorded).toBe(groupRecordedFact(tasks, "good"));
  });
});

describe("bulkDraft: дефицит", () => {
  it("дефицита нет, пока факт влезает в потолки", () => {
    const tasks = [makeTask({ id: 1 })];
    expect(draftShortage(tasks, { 1: { good: "10", defect: "0" } })).toBeNull();
  });

  it("называет излишек сверх лимита", () => {
    const tasks = [makeTask({ id: 1 })];
    expect(draftShortage(tasks, { 1: { good: "13", defect: "0" } })).toEqual({
      fact: 13,
      limit: 10,
      excess: 3,
    });
  });

  it("раскрой в расчёт дефицита не входит: у него нет стратегии", () => {
    const tasks = [
      makeTask({
        id: 1,
        transforms_dimensions: true,
        input_quantity: "10",
        input_consumed_quantity: "0",
        outputs: [{ row_number: 1, quantity: "10" }],
      }),
    ];

    expect(draftShortage(tasks, { 1: { good: "99", defect: "0" } })).toBeNull();
  });
});

describe("bulkDraft: пачка записей", () => {
  it("в пачку уходят только заполненные задания", () => {
    const tasks = [makeTask({ id: 1 }), makeTask({ id: 2 })];
    const draft = withDraftField(withDraftField({}, 1, "good", "3"), 2, "defect", "");

    expect(draftEntries(tasks, draft)).toEqual({
      entries: [
        { taskId: 1, good: entryField(3, "set"), defect: entryField(0) },
      ],
      skipped: [],
    });
  });

  it("недоводимое задание не теряется молча — уходит в skipped", () => {
    const tasks = [
      makeTask({ id: 1 }),
      makeTask({ id: 2, status: "waiting_previous" }),
      makeTask({ id: 3, status: "completed" }),
    ];
    const draft = withDraftField(
      withDraftField(withDraftField({}, 2, "good", "4"), 3, "good", "1"),
      1,
      "good",
      "2",
    );

    const { entries, skipped } = draftEntries(tasks, draft);
    expect(entries).toEqual([{ taskId: 1, good: entryField(2, "set"), defect: entryField(0) }]);
    expect(skipped.map((task) => task.id)).toEqual([2, 3]);
  });

  it("итог «к записи» считается по пачке, а не по черновику", () => {
    expect(
      draftEntryTotals([
        { taskId: 1, good: entryField(3), defect: entryField(1) },
        { taskId: 2, good: entryField(5), defect: entryField(0) },
      ]),
    ).toEqual({ good: 8, defect: 1 });
  });
});

describe("bulkDraft: два режима ввода факта", () => {
  it("«+N» в поле группы раскладывается порциями со знаком", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "40" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "0" } }),
    ];
    const draft = applyGroupField({}, tasks, "good", "+30");

    expect(draftQtyFor(draft, 1).good).toBe("+30");
    expect(draftQtyFor(draft, 2).good).toBe("");
    // Поле группы показывает добавку: сумма порций.
    expect(groupDraftValue(tasks, draft, "good")).toBe("+30");
  });

  it("цель в поле группы раскладывается целями строк: «факт группы станет N»", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "40" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "0" } }),
    ];
    // Записано 40, цель 60 — разница 20 садится в первую строку.
    const draft = applyGroupField({}, tasks, "good", "60");

    expect(draftQtyFor(draft, 1).good).toBe("60");
    expect(draftQtyFor(draft, 2).good).toBe("");
    // Поле группы показывает цель: сумма целей строк.
    expect(groupDraftValue(tasks, draft, "good")).toBe("60");
  });

  it("цель ниже записанного не раскладывается: строки остаются как были", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "100", completed_quantity: "40" } }),
    ];
    const before = applyGroupField({}, tasks, "good", "+5");

    expect(applyGroupField(before, tasks, "good", "10")).toBe(before);
    expect(resolveGroupFact(tasks, "good", "10").resolution.kind).toBe("invalid");
  });

  it("порция записи считается от записанного: «500» при 400 — это 100", () => {
    const task = makeTask({
      id: 1,
      cache: { ...makeTask().cache, issued_quantity: "1000", completed_quantity: "400" },
    });
    const { entries } = draftEntries([task], withDraftField({}, 1, "good", "500"));

    expect(entries).toEqual([
      { taskId: 1, good: { quantity: 100, mode: "set", recorded: 400, target: 500 }, defect: entryField(0) },
    ]);
  });

  it("показ записи: «+100» для добавки и «400 → 500» для цели", () => {
    const task = makeTask({
      id: 1,
      cache: { ...makeTask().cache, issued_quantity: "1000", completed_quantity: "400" },
    });

    const added = draftEntries([task], withDraftField({}, 1, "good", "+100")).entries;
    expect(draftEntryFieldSummary(added, "good")).toBe("+100");

    const set = draftEntries([task], withDraftField({}, 1, "good", "500")).entries;
    expect(draftEntryFieldSummary(set, "good")).toBe("400 → 500");
  });

  it("итоги «к записи» считаются порциями, а не набранными числами", () => {
    const task = makeTask({
      id: 1,
      cache: { ...makeTask().cache, issued_quantity: "1000", completed_quantity: "400" },
    });

    expect(draftTotals([task], withDraftField({}, 1, "good", "500")).good).toBe(100);
    expect(draftTotals([task], withDraftField({}, 1, "good", "+500")).good).toBe(500);
  });
});

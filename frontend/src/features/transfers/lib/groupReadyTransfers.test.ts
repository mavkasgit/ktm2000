import { describe, expect, it } from "vitest";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import {
  groupReadyTransfers,
  nextStepLabel,
  type ReadyTransferGroup,
  type ReadyTransferRowItem,
} from "./groupReadyTransfers";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: null,
    operation_name: "Пила",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "50",
    completed_quantity: "350",
    already_transferred_quantity: "0",
    transferable_quantity: "50",
    has_next_step: true,
    next_section_id: 4,
    next_section_code: "SHOT_BLAST",
    next_section_name: "Дробеструй",
    next_operation_name: "Дробеструй",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

function groupsOf(items: ReadyTransferRowItem[]): ReadyTransferGroup[] {
  return items.filter((item): item is ReadyTransferGroup => item.kind === "group");
}

describe("groupReadyTransfers", () => {
  it("собирает строки одного артикула, участка, размера и адресата в одну группу, сохраняя порядок входа", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11 }),
      makeTask({ task_id: 2, plan_position_id: 12 }),
      makeTask({ task_id: 3, plan_position_id: 13 }),
    ]);

    expect(items).toHaveLength(1);
    const [group] = groupsOf(items);
    expect(group.rows.map((row) => row.task_id)).toEqual([1, 2, 3]);
    expect(group.productSku).toBe("ЮП-2083");
    expect(group.sectionId).toBe(1);
    expect(group.nextSectionId).toBe(4);
  });

  it("разделяет выходы раскроя разных размеров, снятые с одного участка", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, dimensions: { length_mm: 900 }, dimensions_label: "0,9 м" }),
      makeTask({ task_id: 2, dimensions: { length_mm: 1350 }, dimensions_label: "1,35 м" }),
      makeTask({ task_id: 3, dimensions: { length_mm: 1800 }, dimensions_label: "1,8 м" }),
      makeTask({ task_id: 4, dimensions: { length_mm: 2700 }, dimensions_label: "2,7 м" }),
    ]);

    expect(items.map((item) => item.kind)).toEqual(["single", "single", "single", "single"]);
    expect(
      items.map((item) => (item.kind === "single" ? item.row.dimensions : null)),
    ).toEqual([{ length_mm: 900 }, { length_mm: 1350 }, { length_mm: 1800 }, { length_mm: 2700 }]);
  });

  it("разделяет один размер, уходящий разным адресатам (анод: склад ПФ против склада ГП)", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, next_section_id: 4, next_section_code: "PF_STOCK" }),
      makeTask({ task_id: 2, next_section_id: 4, next_section_code: "PF_STOCK" }),
      makeTask({ task_id: 3, next_section_id: 7, next_section_code: "GP_STOCK" }),
      makeTask({ task_id: 4, next_section_id: 7, next_section_code: "GP_STOCK" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.nextSectionId)).toEqual([4, 7]);
    expect(groups[0].rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(groups[1].rows.map((row) => row.task_id)).toEqual([3, 4]);
  });

  it("разделяет один артикул одного размера, лежащий на разных участках", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, section_id: 1 }),
      makeTask({ task_id: 2, section_id: 1 }),
      makeTask({ task_id: 3, section_id: 5, section_code: "ANODE", section_name: "Анод" }),
      makeTask({ task_id: 4, section_id: 5, section_code: "ANODE", section_name: "Анод" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.sectionId)).toEqual([1, 5]);
    expect(groups[0].rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(groups[1].rows.map((row) => row.task_id)).toEqual([3, 4]);
  });

  it("разделяет разные операции одного артикула, размера и адресата («Окно» против «Гребенки»)", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, operation_name: "Окно" }),
      makeTask({ task_id: 2, operation_name: "Окно" }),
      makeTask({ task_id: 3, operation_name: "Гребенка" }),
      makeTask({ task_id: 4, operation_name: "Гребенка" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    // Этап в шапке — общий для группы, а не прочерк: смешанные работы в одной
    // строке обещали один «Передать» на две разные работы.
    expect(groups.map((group) => group.common.operationName)).toEqual(["Окно", "Гребенка"]);
  });

  it("собирает артикулы подряд, а сами артикулы — по сумме «к передаче»", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, product_sku: "АА-1", operation_name: "Окно", transferable_quantity: "100" }),
      makeTask({ task_id: 2, product_sku: "ББ-2", operation_name: "Пила", transferable_quantity: "900" }),
      makeTask({ task_id: 3, product_sku: "АА-1", operation_name: "Гребенка", transferable_quantity: "100" }),
      makeTask({ task_id: 4, product_sku: "ББ-2", operation_name: "Раскрой", transferable_quantity: "900" }),
    ]);

    // Блоков четыре (по операции на артикул), в ответе они перемешаны; после
    // раскладки артикул читается одним куском.
    expect(items.map((item) => (item.kind === "group" ? item.productSku : item.row.product_sku))).toEqual(
      ["ББ-2", "ББ-2", "АА-1", "АА-1"],
    );
  });

  it("разделяет разные артикулы одного размера на одном участке", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, product_sku: "ЮП-2083" }),
      makeTask({ task_id: 2, product_sku: "ЮП-2083" }),
      makeTask({ task_id: 3, product_sku: "ЮП-3270" }),
      makeTask({ task_id: 4, product_sku: "ЮП-3270" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.productSku)).toEqual(["ЮП-2083", "ЮП-3270"]);
  });

  it("сводит `null` и `{}` в один безразмерный ключ, но не сливает его с размерными строками", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, dimensions: null, dimensions_label: null }),
      makeTask({ task_id: 2, dimensions: {}, dimensions_label: null }),
      makeTask({ task_id: 3, dimensions: { length_mm: 900 }, dimensions_label: "0,9 м" }),
    ]);

    expect(items).toHaveLength(2);
    const [dimensionless] = groupsOf(items);
    expect(dimensionless.rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(items[1].kind).toBe("single");
    expect(items[1].kind === "single" ? items[1].row.task_id : null).toBe(3);
  });

  it("оставляет единственную строку по ключу одиночной", () => {
    const items = groupReadyTransfers([makeTask({ task_id: 7 })]);

    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe("single");
    expect(items[0].kind === "single" ? items[0].row.task_id : null).toBe(7);
  });

  it("суммирует transferable_quantity по строкам группы", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, transferable_quantity: "50" }),
      makeTask({ task_id: 2, transferable_quantity: "25" }),
      makeTask({ task_id: 3, transferable_quantity: "10" }),
    ]);

    const [group] = groupsOf(items);
    expect(group.totalTransferable).toBe(85);
  });

  it("суммирует план и уже переданное по строкам группы", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, planned_quantity: "100", already_transferred_quantity: "0" }),
      makeTask({ task_id: 2, planned_quantity: "50", already_transferred_quantity: "10" }),
      makeTask({ task_id: 3, planned_quantity: "25", already_transferred_quantity: "15" }),
    ]);

    const [group] = groupsOf(items);
    expect(group.totalPlanned).toBe(175);
    expect(group.totalAlreadyTransferred).toBe(25);
  });

  it("помечает группу финальной, только когда финальна каждая её строка", () => {
    const allFinal = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: true, has_next_step: false }),
      makeTask({ task_id: 2, is_final: true, has_next_step: false }),
    ]);
    expect(groupsOf(allFinal)[0].allFinal).toBe(true);

    const mixed = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: true, has_next_step: false }),
      makeTask({ task_id: 2, is_final: false, has_next_step: true }),
    ]);
    expect(groupsOf(mixed)[0].allFinal).toBe(false);

    // `!has_next_step` в UI — тот же финальный выпуск, что и `is_final`.
    const noNextStep = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: false, has_next_step: false }),
      makeTask({ task_id: 2, is_final: false, has_next_step: false }),
    ]);
    expect(groupsOf(noNextStep)[0].allFinal).toBe(true);
  });

  it("сводные значения группы считаются по строкам: расходится следующая операция — прочерк, этап всегда один", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, next_operation_name: "Дробеструй" }),
      makeTask({ task_id: 2, next_operation_name: "Дробеструй" }),
      makeTask({ task_id: 3, next_operation_name: "Дробеструй, П/ф" }),
      makeTask({ task_id: 4, next_operation_name: "Дробеструй, П/ф" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(1);
    // Этап — часть ключа, поэтому в сводке он всегда один. Прочерк остаётся у
    // значений, которые ключ не различает: следующая операция может разойтись
    // при общем адресате (участок тот же, работа на нём — разная).
    expect(groups[0].common.operationName).toBe("Пила");
    expect(groups[0].common.nextOperationName).toBeNull();
    expect(groups[0].common.dimensionsLabel).toBe("2,75 м");
    expect(groups[0].common.nextSectionName).toBe("Дробеструй");
  });

  it("печатает размер строки, даже если сервер не прислал подпись (#195)", () => {
    // `dimensions_label` в контракте nullable. Раньше группа брала только
    // серверную подпись и печатала «—» — та же ячейка на доске в этот момент
    // показывала «2,75 м».
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11, dimensions_label: null }),
      makeTask({ task_id: 2, plan_position_id: 12, dimensions_label: null }),
    ]);

    expect(groupsOf(items)[0].common.dimensionsLabel).toBe("2,75 м");
  });

  it("безразмерные строки группы печатают прочерк, а не пустую строку (#195)", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11, dimensions: null, dimensions_label: null }),
      makeTask({ task_id: 2, plan_position_id: 12, dimensions: {}, dimensions_label: null }),
    ]);

    expect(groupsOf(items)[0].common.dimensionsLabel).toBe("—");
  });

  it("отдаёт в common название следующего участка, а при расхождении строк — null", () => {
    // Название участка в подписи колонки «Следующий» — единственный адресат
    // складского этапа, где операций нет. Общее значение расходится, значит
    // подписи у строк группы разные, и свёрнутая строка не имеет права
    // показывать участок ни одной из них.
    const agreed = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11, next_section_name: "Склад полуфабриката" }),
      makeTask({ task_id: 2, plan_position_id: 12, next_section_name: "Склад полуфабриката" }),
    ]);
    expect(groupsOf(agreed)[0].common.nextSectionName).toBe("Склад полуфабриката");

    const diverged = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11, next_section_name: "Склад полуфабриката" }),
      makeTask({ task_id: 2, plan_position_id: 12, next_section_name: "Склад готовой продукции" }),
    ]);
    expect(groupsOf(diverged)[0].common.nextSectionName).toBeNull();
  });
});

/**
 * Подпись адресата передачи: операция приоритетнее названия участка, а когда
 * нет ни того, ни другого — прочерк. Складские этапы (`next_operation_name`
 * === null) обязаны печатать название участка, иначе адресат пропадал бы.
 */
describe("nextStepLabel", () => {
  it("печатает операцию, не добавляя к ней код участка и номер этапа", () => {
    expect(nextStepLabel("Хранение: Склад готовой продукции", "Склад готовой продукции")).toBe(
      "Хранение: Склад готовой продукции",
    );
  });

  it("без операции печатает название участка — так у складских этапов", () => {
    expect(nextStepLabel(null, "Склад полуфабриката")).toBe("Склад полуфабриката");
  });

  it("без операции и без участка печатает прочерк, а не пустую ячейку", () => {
    expect(nextStepLabel(null, null)).toBe("—");
    expect(nextStepLabel("", "")).toBe("—");
  });
});

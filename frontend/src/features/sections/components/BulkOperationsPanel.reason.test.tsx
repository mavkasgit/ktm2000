/**
 * Причина, по которой «Подтвердить» в панели массовых операций не нажимается,
 * видна на экране (#193).
 *
 * Контракт: у кнопки ровно одна причина, и она та, что мешает именно сейчас.
 * Два разных случая раньше выглядели одинаково — серая кнопка без слов:
 * завершать нечего вовсе и количество не введено. Оператор обязан различать их
 * без наведения мыши, иначе он не понимает, что ему делать.
 *
 * Формулировки не пиню: текст берётся из словаря по коду.
 */

import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { BulkOperationsPanel } from "./BulkOperationsPanel";

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
    status: "in_progress",
    cache: {
      available_quantity: "10",
      issued_quantity: "10",
      completed_quantity: "4",
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

function renderPanel(tasks: SectionBoardTask[]): HTMLElement {
  const { container } = render(
    <BulkOperationsPanel tasks={tasks} onExecuteAll={vi.fn()} pending={false} />,
  );
  return container;
}

/**
 * Тексты причин рядом с кнопкой: подписи-элементы в одной с ней строке.
 * Баннер «Будет пропущено» живёт в другой части панели и сюда не попадает —
 * иначе проверка не отличала бы «объяснили у кнопки» от «упомянули где-то».
 */
function reasonTextsBesideConfirm(container: HTMLElement): string[] {
  const confirm = within(container).getByRole("button", { name: "Подтвердить" });
  const row = confirm.parentElement;
  if (!row) throw new Error("кнопка вне контейнера");
  return Array.from(row.children)
    .filter((node): node is HTMLElement => node.tagName === "SPAN" && node.hasAttribute("title"))
    .map((node) => node.textContent ?? "");
}

function confirmButton(container: HTMLElement): HTMLElement {
  return within(container).getByRole("button", { name: "Подтвердить" });
}

describe("BulkOperationsPanel: причина недоступности «Подтвердить» видна на экране", () => {
  it("завершать нечего: у кнопки видна именно эта причина, а не «введите количество»", () => {
    const container = renderPanel([makeTask({ id: 1, status: "waiting_previous" })]);

    expect(reasonTextsBesideConfirm(container)).toEqual([
      actionReasonText("bulk_nothing_to_complete"),
    ]);
    // Причины читаются по-разному: оператор обязан отличить «нечего завершать»
    // от «введите количество» — обе выглядят серой кнопкой без слов.
    expect(actionReasonText("bulk_nothing_to_complete")).not.toBe(
      actionReasonText("bulk_no_quantity"),
    );
    expect(confirmButton(container).hasAttribute("disabled")).toBe(true);
  });

  it("задания завершаемы, но количество не введено: видна причина про количество", () => {
    const container = renderPanel([makeTask({ id: 1 })]);

    expect(reasonTextsBesideConfirm(container)).toEqual([actionReasonText("bulk_no_quantity")]);
    expect(confirmButton(container).hasAttribute("disabled")).toBe(true);
  });

  it("после ввода количества лишнего текста у кнопки не остаётся", () => {
    const container = renderPanel([makeTask({ id: 1 })]);

    // Первое числовое поле группы — «+ Добавить».
    const addQty = container.querySelector('input[inputmode="numeric"]');
    if (!addQty) throw new Error("в группе нет поля количества");
    fireEvent.change(addQty, { target: { value: "3" } });

    expect(reasonTextsBesideConfirm(container)).toEqual([]);
    expect(confirmButton(container).hasAttribute("disabled")).toBe(false);
  });
});

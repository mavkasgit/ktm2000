/**
 * Диалог ручного пропуска этапа (#348): причина обязательна.
 *
 * Пропуск без причины — это «сделали вид, что работы не было» без ответа на
 * вопрос «почему». Поэтому пустое и пробельное поле не отправляется, а
 * серверная ручка отвечает на него 400.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { SkipStageDialog } from "./SkipStageDialog";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 5,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 3,
    operation_code: "op",
    operation_name: "Анодирование",
    is_significant: true,
    planned_quantity: "10",
    status: "in_progress",
    cache: {
      available_quantity: "10",
      issued_quantity: "10",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "10",
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

function renderDialog(onSubmit = vi.fn()) {
  render(
    <SkipStageDialog
      open
      onOpenChange={vi.fn()}
      task={makeTask()}
      pending={false}
      onSubmit={onSubmit}
    />,
  );
  return onSubmit;
}

const reasonField = () =>
  screen.getByLabelText("Причина пропуска") as HTMLTextAreaElement;
const confirmButton = () =>
  screen.getByRole("button", { name: "Пропустить" }) as HTMLButtonElement;

describe("SkipStageDialog: причина обязательна (#348)", () => {
  it("называет этап, который пропускают", () => {
    renderDialog();

    expect(screen.getByText("Пропустить этап")).toBeTruthy();
    expect(screen.getByText(/Анодирование.*Этап #3/)).toBeTruthy();
  });

  it("пустая причина не отправляется: кнопка выключена", () => {
    const onSubmit = renderDialog();

    expect(confirmButton().disabled).toBe(true);
    fireEvent.click(confirmButton());

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("пробельная причина не считается введённой", () => {
    const onSubmit = renderDialog();

    fireEvent.change(reasonField(), { target: { value: "   " } });

    expect(confirmButton().disabled).toBe(true);
    fireEvent.click(confirmButton());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("введённая причина уходит на сервер без пробелов по краям", () => {
    const onSubmit = renderDialog();

    fireEvent.change(reasonField(), {
      target: { value: "  Материал подан в готовом виде  " },
    });
    expect(confirmButton().disabled).toBe(false);
    fireEvent.click(confirmButton());

    expect(onSubmit).toHaveBeenCalledWith("Материал подан в готовом виде");
  });

  it("готовая причина подставляется одним нажатием", () => {
    const onSubmit = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Материал подан в готовом виде" }));
    fireEvent.click(confirmButton());

    expect(onSubmit).toHaveBeenCalledWith("Материал подан в готовом виде");
  });

  it("пока запрос в работе, повторно не отправляет", () => {
    const onSubmit = vi.fn();
    render(
      <SkipStageDialog
        open
        onOpenChange={vi.fn()}
        task={makeTask()}
        pending
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(reasonField(), { target: { value: "Переделка не нужна" } });
    fireEvent.click(confirmButton());

    expect(onSubmit).not.toHaveBeenCalled();
  });
});

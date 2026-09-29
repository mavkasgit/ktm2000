/**
 * Причина, по которой «Передать все» в групповой передаче не нажимается, видна
 * на экране (#193).
 *
 * Контракт: у кнопки ровно одна причина, и она меняется по мере заполнения
 * формы — сначала «задания не выбраны», потом «не выбран исполнитель», потом
 * причина исчезает совсем. Раньше это была серая кнопка без слов, и оператор
 * не понимал, что ему предлагают изменить.
 *
 * Формулировки не пиню: текст берётся из словаря по коду.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import type { BulkRunnerProgress } from "@/shared/bulk";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { useAuth, type AuthShellUser } from "@/features/auth/hooks/useAuth";
import { BulkTransferFooter } from "./BulkTransferFooter";

vi.mock("@/features/auth/hooks/useAuth", () => ({ useAuth: vi.fn() }));

vi.mock("@/shared/api/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/users")>()),
  listUsers: vi.fn().mockResolvedValue([]),
}));

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: "010",
    operation_name: "Пила",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "100",
    completed_quantity: "100",
    already_transferred_quantity: "0",
    transferable_quantity: "100",
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

function setUser(user: AuthShellUser | null) {
  vi.mocked(useAuth).mockReturnValue({
    user,
    rolesCatalog: [],
    roleLabel: (role: string) => role,
    roleSections: () => [],
    isAuthenticated: user !== null,
    isLoading: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  });
}

function renderFooter(
  selectedTasks: ReadyToTransferTask[],
  options: { pending?: boolean; progress?: BulkRunnerProgress | null } = {},
): HTMLElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <BulkTransferFooter
        selectedTasks={selectedTasks}
        onSubmit={vi.fn()}
        onExit={vi.fn()}
        onClearSelection={vi.fn()}
        pending={options.pending ?? false}
        progress={options.progress ?? null}
      />
    </QueryClientProvider>,
  );
  return container;
}

function submitButton(container: HTMLElement): HTMLElement {
  return within(container).getByRole("button", { name: /^Передать все/ });
}

/**
 * Тексты причин рядом с кнопкой: подписи-элементы в одной с ней строке.
 * `title` самой кнопки сюда не попадает — без наведения мыши он не виден.
 */
function reasonTextsBeside(button: HTMLElement): string[] {
  const row = button.parentElement;
  if (!row) throw new Error("кнопка вне контейнера");
  return Array.from(row.children)
    .filter((node): node is HTMLElement => node.tagName === "SPAN" && node.hasAttribute("title"))
    .map((node) => node.textContent ?? "");
}

function reasonTextsBesideSubmit(container: HTMLElement): string[] {
  return reasonTextsBeside(submitButton(container));
}

describe("BulkTransferFooter: причина недоступности «Передать все» видна на экране", () => {
  beforeEach(() => {
    setUser({ id: 7, username: "operator", full_name: "Иванов", role: "operator" });
  });

  it("без выбранных заданий у кнопки видна причина «выбрать задания»", () => {
    const container = renderFooter([]);

    expect(reasonTextsBesideSubmit(container)).toEqual([actionReasonText("no_tasks_selected")]);
    expect(submitButton(container).hasAttribute("disabled")).toBe(true);
  });

  it("задания выбраны, но исполнитель ещё не определён — видна другая причина", () => {
    // Профиль оператора без id: подставить исполнителя пока нечем.
    setUser({ id: null, username: "operator", full_name: "Иванов", role: "operator" });
    const container = renderFooter([makeTask({ task_id: 1 }), makeTask({ task_id: 2 })]);

    expect(reasonTextsBesideSubmit(container)).toEqual([actionReasonText("no_executor")]);
    // Причины читаются по-разному: оператор обязан отличить «исполнителя
    // выберите» от «задания выберите» — обе грозят серой кнопкой.
    expect(actionReasonText("no_executor")).not.toBe(actionReasonText("no_tasks_selected"));
    expect(submitButton(container).hasAttribute("disabled")).toBe(true);
  });

  it("когда всё заполнено, лишнего текста у кнопки не остаётся", () => {
    const container = renderFooter([makeTask({ task_id: 1 })]);

    expect(reasonTextsBesideSubmit(container)).toEqual([]);
    expect(submitButton(container).hasAttribute("disabled")).toBe(false);
  });

  it("идущая передача не выдумывает причину: о ней говорит надпись на кнопке", () => {
    const container = renderFooter([makeTask({ task_id: 1 })], {
      pending: true,
      progress: { running: true, total: 2, completed: 1 },
    });

    // Временное состояние — не причина недоступности: второй текст рядом с
    // кнопкой был бы шумом.
    const running = within(container).getByRole("button", { name: "Отправка..." });
    expect(reasonTextsBeside(running)).toEqual([]);
  });
});

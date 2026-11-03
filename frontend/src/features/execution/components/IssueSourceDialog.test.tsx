// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IssuePreviewCandidate, IssuePreviewOut } from "@/shared/api/productionPlans";

vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  issuePreview: vi.fn(),
}));

import { issuePreview } from "@/shared/api/productionPlans";
import { IssueSourceDialog } from "./IssueSourceDialog";

const candidate = (over: Partial<IssuePreviewCandidate>): IssuePreviewCandidate => ({
  balance_id: 1,
  location_id: 1,
  location_name: "Склад",
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

const preview = (over: Partial<IssuePreviewOut>): IssuePreviewOut => ({
  position_id: 1,
  product_id: 1,
  required: "30",
  required_dimensions: null,
  required_dimensions_label: null,
  collected: "30",
  deficit: "0",
  candidates: [],
  hints: [],
  ...over,
});

function mountDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IssueSourceDialog
        open
        onOpenChange={() => {}}
        positionId={1}
        positionSku="SKU-1"
        positionName="Изделие"
        pending={false}
        onConfirm={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("IssueSourceDialog: порядок строк = серверный `order` (#282)", () => {
  it("печатает кандидатов ровно как пришёл список — без локальной сортировки", async () => {
    // Массив в порядке `order`, но НЕ по алфавиту и НЕ по id: своё сравнение
    // здесь ломает смысл подбора — очередь выдачи считает сервер.
    vi.mocked(issuePreview).mockResolvedValue(
      preview({
        candidates: [
          candidate({ balance_id: 3, location_id: 30, location_name: "Гамма", order: 0 }),
          candidate({ balance_id: 1, location_id: 10, location_name: "Альфа", order: 1 }),
          candidate({ balance_id: 2, location_id: 20, location_name: "Бета", order: 2 }),
        ],
      }),
    );

    mountDialog();
    await screen.findByTestId("issue-candidate-row-3");

    // Radix рендерит окно в портал на `document.body`, а не внутри контейнера
    // рендера — читаем порядок строк прямо из документа.
    const rendered = [...document.querySelectorAll('[data-testid^="issue-candidate-row-"]')].map(
      (el) => el.getAttribute("data-testid")?.replace("issue-candidate-row-", ""),
    );
    expect(rendered).toEqual(["3", "1", "2"]);
  });
});

describe("IssueSourceDialog: снятая галочка → новый preview и подсказка пропадает", () => {
  it("повторный вызов уходит с `excluded_balance_ids`, подсказка по снятому складу гаснет", async () => {
    vi.mocked(issuePreview).mockImplementation(async (_id, payload) => {
      const excluded = payload?.excluded_balance_ids ?? [];
      if (excluded.includes(2)) {
        // Склад снят: он `included: false`, и подсказка по нему не нужна.
        return preview({
          candidates: [
            candidate({ balance_id: 1, location_id: 1, location_name: "Склад 1", included: true }),
            candidate({ balance_id: 2, location_id: 2, location_name: "Склад 2", included: false }),
          ],
          hints: [{ kind: "defect", location_id: 1, location_name: "Склад 1", quantity: "1", text: "Брак на складе 1" }],
        });
      }
      return preview({
        candidates: [
          candidate({ balance_id: 1, location_id: 1, location_name: "Склад 1" }),
          candidate({ balance_id: 2, location_id: 2, location_name: "Склад 2" }),
        ],
        hints: [
          { kind: "defect", location_id: 1, location_name: "Склад 1", quantity: "1", text: "Брак на складе 1" },
          { kind: "other_size", location_id: 2, location_name: "Склад 2", quantity: "3", text: "Другой размер на складе 2" },
        ],
      });
    });

    mountDialog();
    await screen.findByTestId("issue-hint-2-other_size");

    fireEvent.click(screen.getByRole("checkbox", { name: /Склад 2/ }));

    // Снятие живёт ровно этот вызов: новый preview с `excluded_balance_ids`.
    await waitFor(() => {
      const calls = vi.mocked(issuePreview).mock.calls;
      const last = calls[calls.length - 1]?.[1];
      expect(last?.excluded_balance_ids).toEqual([2]);
    });
    await waitFor(() => {
      expect(screen.queryByTestId("issue-hint-2-other_size")).toBeNull();
      // Подсказка по оставленному складу остаётся.
      expect(screen.getByTestId("issue-hint-1-defect")).toBeTruthy();
    });
  });
});

describe("IssueSourceDialog: disabled-кнопка с серверной причиной (#282)", () => {
  it("при 400 от сервера кнопка неактивна, а видна серверная `detail`", async () => {
    vi.mocked(issuePreview).mockRejectedValue({
      response: { status: 400, data: { detail: "Недостаточно остатка для выбранной стратегии" } },
    });

    mountDialog();

    // До того как обещание отклонится, виден «Считаем подбор склада…»; ждём
    // именно серверную причину отказа.
    await waitFor(() => {
      const reason = screen.getByTestId("issue-confirm-reason");
      // Своя формулировка не выдумывается — берётся серверная.
      expect(reason.textContent).toContain("Недостаточно остатка для выбранной стратегии");
    });

    await waitFor(() => {
      const button = screen.getByTestId("issue-confirm-launch") as HTMLButtonElement;
      expect(button.disabled).toBe(true);
    });
  });
});

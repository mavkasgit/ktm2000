// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const preview = (over: Partial<IssuePreviewOut>): IssuePreviewOut => ({
  position_id: 1,
  product_id: 1,
  group_key: 1,
  group_skus: ["SKU-1"],
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
  it("печатает строки групп по минимальному `order` — без локальной сортировки", async () => {
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
    await screen.findByTestId("issue-candidate-group-0-30-0");

    // Radix рендерит окно в портал на `document.body`, а не внутри контейнера
    // рендера — читаем порядок строк прямо из документа.
    const rendered = [
      ...document.querySelectorAll('[data-testid^="issue-candidate-group-"]'),
    ].map((el) => el.getAttribute("data-testid")?.replace("issue-candidate-group-", ""));
    expect(rendered).toEqual(["0-30-0", "0-10-1", "0-20-2"]);
  });

  it("строка группы встаёт по минимальному order своих кандидатов", async () => {
    vi.mocked(issuePreview).mockResolvedValue(
      preview({
        candidates: [
          candidate({ balance_id: 1, location_id: 10, location_name: "Альфа", order: 0 }),
          candidate({ balance_id: 2, location_id: 20, location_name: "Бета", order: 1 }),
          // Та же строка (склад + размер + операции), но очередь дошла позже.
          candidate({ balance_id: 3, location_id: 10, location_name: "Альфа", order: 2 }),
        ],
      }),
    );

    mountDialog();
    await screen.findByTestId("issue-candidate-group-0-10-0");

    const rendered = [
      ...document.querySelectorAll('[data-testid^="issue-candidate-group-"]'),
    ].map((el) => el.getAttribute("data-testid")?.replace("issue-candidate-group-", ""));
    expect(rendered).toEqual(["0-10-0", "0-20-1"]);
  });
});

describe("IssueSourceDialog: группа эквивалентов одной строкой (#396)", () => {
  const groupPreview = () =>
    preview({
      product_id: 100,
      group_key: 5,
      group_skus: ["A", "B"],
      candidates: [
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
          order: 0,
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
          order: 1,
        }),
      ],
    });

  it("две SKU — одна строка с суммами, подписью группы и пометкой артикула задания", async () => {
    vi.mocked(issuePreview).mockResolvedValue(groupPreview());

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-5-10-0");

    expect(row.textContent).toContain("A, B (эквиваленты)");
    // Артикул задания помечен: строка-эквивалент — не ошибка.
    expect(row.textContent).toContain("артикул задания");
    // Суммы серверных значений, а не пересчёт: 10 + 5.
    expect(within(row).getAllByText("15")).toHaveLength(2);

    // До раскрытия фактических SKU-строк нет — порядок и числа не меняются.
    expect(screen.queryByTestId("issue-candidate-row-1")).toBeNull();
    expect(screen.queryByTestId("issue-candidate-row-2")).toBeNull();
  });

  it("раскрытие показывает фактические SKU-строки с их balance_id", async () => {
    vi.mocked(issuePreview).mockResolvedValue(groupPreview());

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-5-10-0");
    fireEvent.click(within(row).getByTestId("issue-candidate-expand-5-10-0"));

    const first = await screen.findByTestId("issue-candidate-row-1");
    const second = await screen.findByTestId("issue-candidate-row-2");
    expect(first.textContent).toContain("A");
    expect(second.textContent).toContain("B");
    expect(within(first).getByRole("checkbox")).toBeTruthy();
    expect(within(second).getByRole("checkbox")).toBeTruthy();
  });

  it("снятие галочки группы исключает все её balance_id", async () => {
    vi.mocked(issuePreview).mockResolvedValue(groupPreview());

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-5-10-0");
    fireEvent.click(within(row).getByRole("checkbox"));

    await waitFor(() => {
      const calls = vi.mocked(issuePreview).mock.calls;
      const last = calls[calls.length - 1]?.[1];
      expect(last?.excluded_balance_ids).toEqual([1, 2]);
    });
  });

  it("частичное снятие внутри группы — indeterminate, исключён только один balance_id", async () => {
    vi.mocked(issuePreview).mockResolvedValue(groupPreview());

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-5-10-0");
    fireEvent.click(within(row).getByTestId("issue-candidate-expand-5-10-0"));
    fireEvent.click(within(await screen.findByTestId("issue-candidate-row-1")).getByRole("checkbox"));

    await waitFor(() => {
      const calls = vi.mocked(issuePreview).mock.calls;
      const last = calls[calls.length - 1]?.[1];
      expect(last?.excluded_balance_ids).toEqual([1]);
    });
    expect(within(row).getByRole("checkbox").getAttribute("aria-checked")).toBe("mixed");
  });

  it("строка только из эквивалента помечена «эквивалент»", async () => {
    // На складе лежит только B, артикул задания — A: строка законна, но
    // оператор должен видеть, что материал другого SKU группы (ADR-0073 п.5).
    vi.mocked(issuePreview).mockResolvedValue(
      preview({
        product_id: 100,
        group_key: 5,
        group_skus: ["A", "B"],
        candidates: [
          candidate({
            balance_id: 2,
            location_id: 10,
            group_key: 5,
            product_id: 200,
            sku: "B",
          }),
        ],
      }),
    );

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-5-10-0");

    expect(row.textContent).toContain("эквивалент");
    expect(row.textContent).not.toContain("артикул задания");
  });

  it("одиночная строка группы не требует раскрытия", async () => {
    vi.mocked(issuePreview).mockResolvedValue(
      preview({
        candidates: [candidate({ balance_id: 7, location_id: 10, sku: "A" })],
      }),
    );

    mountDialog();
    const row = await screen.findByTestId("issue-candidate-group-0-10-0");
    expect(within(row).queryByTestId("issue-candidate-expand-0-10-0")).toBeNull();
    // Старый id SKU-строки сохранён.
    expect(within(row).getByTestId("issue-candidate-row-7")).toBeTruthy();
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

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type * as ActionsModule from "@/shared/api/actions";

vi.mock("@/shared/api/actions", async (importOriginal) => ({
  ...(await importOriginal<typeof ActionsModule>()),
  previewAmend: vi.fn(),
  amendAction: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({
  toast: vi.fn(),
}));

import { previewAmend, type JournalAction, type PreviewResponse } from "@/shared/api/actions";
import { AmendDialog } from "./AmendDialog";

const action: JournalAction = {
  id: 5,
  action_type: "transfer_send",
  ref_id: 11,
  actor: "Иван",
  status: "active",
  depends_on: [],
  created_at: "2026-08-20T10:00:00Z",
};

const makePreview = (overrides: Partial<PreviewResponse> = {}): PreviewResponse => ({
  action_id: 5,
  cascade: false,
  revert: [],
  stays: [],
  blockers: [],
  plan_token: "tok-1",
  will_replay: [],
  ...overrides,
});

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AmendDialog action={action} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

const quantityField = () => screen.getByTestId("amend-quantity");
const previewButton = () => screen.getByRole("button", { name: /Предпросмотр/i });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(previewAmend).mockResolvedValue(makePreview());
});

describe("AmendDialog — количество", () => {
  it("отправляет на сервер число, а не строку", async () => {
    renderDialog();
    fireEvent.change(quantityField(), { target: { value: "5" } });
    fireEvent.click(previewButton());

    await waitFor(() => expect(previewAmend).toHaveBeenCalled());
    expect(vi.mocked(previewAmend).mock.calls[0][1]).toEqual({ quantity: 5 });
  });

  it("дробь передаётся числом: домен передач дробный", async () => {
    renderDialog();
    fireEvent.change(quantityField(), { target: { value: "0,5" } });
    fireEvent.click(previewButton());

    await waitFor(() => expect(previewAmend).toHaveBeenCalled());
    // `Decimal("0,5")` на сервере бросает исключение — уйти должна точка.
    expect(vi.mocked(previewAmend).mock.calls[0][1]).toEqual({ quantity: 0.5 });
  });

  it("текст в поле отклоняется с видимой причиной и не уходит на сервер", async () => {
    renderDialog();
    fireEvent.change(quantityField(), { target: { value: "абв" } });

    expect((await screen.findByTestId("amend-quantity-issue")).textContent).toMatch(/только цифры/i);

    fireEvent.click(previewButton());
    await waitFor(() => expect(previewAmend).not.toHaveBeenCalled());
  });

  it("ноль отклоняется: сервер требует строго больше нуля", async () => {
    renderDialog();
    fireEvent.change(quantityField(), { target: { value: "0" } });

    expect((await screen.findByTestId("amend-quantity-issue")).textContent).toMatch(/больше нуля/i);

    fireEvent.click(previewButton());
    await waitFor(() => expect(previewAmend).not.toHaveBeenCalled());
  });

  it("причина снимается, когда ввод снова допустим", async () => {
    renderDialog();
    const field = quantityField();
    fireEvent.change(field, { target: { value: "абв" } });
    await screen.findByTestId("amend-quantity-issue");

    fireEvent.change(field, { target: { value: "5" } });
    await waitFor(() => expect(screen.queryByTestId("amend-quantity-issue")).toBeNull());
  });

  it("пустое поле ничего не отправляет — это отсутствие ввода, а не ноль", async () => {
    renderDialog();
    fireEvent.change(quantityField(), { target: { value: "   " } });
    fireEvent.click(previewButton());

    await waitFor(() => expect(previewAmend).toHaveBeenCalled());
    expect(vi.mocked(previewAmend).mock.calls[0][1]).toEqual({});
  });
});

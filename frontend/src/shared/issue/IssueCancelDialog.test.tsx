// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IssueCancelPreview, IssueCancelScenario } from "@/shared/api/transfers";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  previewIssueCancellation: vi.fn(),
  cancelIssue: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({ toast: vi.fn() }));

import { cancelIssue, previewIssueCancellation } from "@/shared/api/transfers";
import { IssueCancelDialog } from "./IssueCancelDialog";

const scenario = (over: Partial<IssueCancelScenario> = {}): IssueCancelScenario => ({
  returns: [
    { transfer_id: 10, transfer_no: "T-10", location_id: 5, location_name: "Хранилище А", quantity: "12" },
  ],
  stages: [{ task_id: 99, sequence: 2, stage_name: "Пиление" }],
  can_cancel: true,
  reason: null,
  summary: "Вернём 12 на «Хранилище А»",
  ...over,
});

const preview = (over: Partial<IssueCancelPreview> = {}): IssueCancelPreview => ({
  issue_no: "ISSUE-1",
  transfers: [
    {
      transfer_id: 10,
      transfer_no: "T-10",
      location_id: 5,
      location_name: "Хранилище А",
      quantity: "12",
      accepted_quantity: "0",
      cancellable: true,
      block_reason: null,
    },
    {
      transfer_id: 11,
      transfer_no: "T-11",
      location_id: 6,
      location_name: "Хранилище Б",
      quantity: "5",
      accepted_quantity: "5",
      cancellable: false,
      block_reason: "Передача T-11 принята частично — в режиме «остаток» её не трогаем",
    },
  ],
  remainder: { ...scenario(), kept: [] },
  full: { ...scenario(), accepted_quantity: "5" },
  ...over,
});

function mount(issueNo: string | null = "ISSUE-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IssueCancelDialog open onOpenChange={() => {}} issueNo={issueNo} />
    </QueryClientProvider>,
  );
}

async function pickMode(mode: "remainder" | "full") {
  const option = await screen.findByTestId(`issue-cancel-mode-${mode}`);
  fireEvent.click(option);
  return option;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("IssueCancelDialog: режим выбирается явно (#349)", () => {
  it("пока режим не выбран, кнопка неактивна и причина видна текстом", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(preview());

    mount();

    const button = (await screen.findByTestId("issue-cancel-confirm")) as HTMLButtonElement;
    await screen.findByTestId("issue-cancel-mode-remainder");
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(screen.getByTestId("issue-cancel-reason").textContent).toContain("Выберите режим");
  });

  it("выбор «остаток» разрешает отмену даже когда полный откат заблокирован", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(
      preview({
        remainder: { ...scenario(), kept: [] },
        full: { ...scenario({ can_cancel: false, reason: "Часть материала уже израсходована" }), accepted_quantity: "5" },
      }),
    );

    mount();
    await pickMode("remainder");

    const button = (await screen.findByTestId("issue-cancel-confirm")) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(button.textContent).toContain("Отменить остаток");

    // Выбор заблокированного режима показывает серверную причину.
    await pickMode("full");
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(screen.getByTestId("issue-cancel-reason").textContent).toContain("уже израсходована");
  });

  it("полный откат показывает, сколько уже принято, и отправляет mode=full", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(preview());
    vi.mocked(cancelIssue).mockResolvedValue({
      issue_no: "ISSUE-1",
      mode: "full",
      idempotent_replay: false,
      cancelled_transfers: [{ transfer_id: 11, transfer_no: "T-11", status: "cancelled", quantity: "5" }],
      kept_transfers: [],
      restored_stages: [{ task_id: 99, sequence: 2, stage_name: "Пиление" }],
      reversed_tx_ids: [1, 2],
    });

    mount();
    await pickMode("full");

    expect((await screen.findByTestId("issue-cancel-full-warning")).textContent).toContain(
      "Уже принято получателем: 5 шт.",
    );

    const button = (await screen.findByTestId("issue-cancel-confirm")) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(cancelIssue).toHaveBeenCalled());
    const [, payload] = vi.mocked(cancelIssue).mock.calls[0];
    expect(payload?.mode).toBe("full");
    expect(payload?.idempotencyKey).toBeTruthy();
  });

  it("`can_cancel: false` в двух режимах — причина из `reason`, отмена запрещена", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(
      preview({
        remainder: {
          ...scenario({ can_cancel: false, reason: "Все передачи уже приняты получателем" }),
          kept: [],
        },
        full: {
          ...scenario({ can_cancel: false, reason: "Недостаточно покрытия для отката" }),
          accepted_quantity: "5",
        },
      }),
    );

    mount();
    await pickMode("full");

    await waitFor(() => {
      const reason = screen.getByTestId("issue-cancel-reason");
      expect(reason.textContent).toContain("Недостаточно покрытия для отката");
    });
    const button = screen.getByTestId("issue-cancel-confirm") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

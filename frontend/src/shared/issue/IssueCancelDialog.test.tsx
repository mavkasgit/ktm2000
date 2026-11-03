// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IssueCancelPreview } from "@/shared/api/transfers";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  previewIssueCancellation: vi.fn(),
  cancelIssue: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({ toast: vi.fn() }));

import { cancelIssue, previewIssueCancellation } from "@/shared/api/transfers";
import { IssueCancelDialog } from "./IssueCancelDialog";

const preview = (over: Partial<IssueCancelPreview>): IssueCancelPreview => ({
  issue_no: "ISSUE-1",
  returns: [
    { transfer_id: 10, transfer_no: "T-10", location_id: 5, location_name: "Хранилище А", quantity: "12" },
  ],
  stages: [{ task_id: 99, sequence: 2, stage_name: "Пиление" }],
  can_cancel: true,
  reason: null,
  summary: "Вернём 12 на «Хранилище А»",
  ...over,
});

function mount(issueNo: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IssueCancelDialog open onOpenChange={() => {}} issueNo={issueNo} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("IssueCancelDialog: отказ сервера показан текстом, действие запрещено (#282)", () => {
  it("`can_cancel: false` → причина из `reason`, кнопка отмены неактивна", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(
      preview({ can_cancel: false, reason: "Передача уже принята получателем — откат невозможен" }),
    );

    mount("ISSUE-1");

    // Пока превью едет, под кнопкой висит «Считаем…»; ждём серверную причину.
    await waitFor(() => {
      const reason = screen.getByTestId("issue-cancel-reason");
      // Своей формулировки нет — серверная причина.
      expect(reason.textContent).toContain("Передача уже принята получателем");
    });
    expect(screen.getByTestId("issue-cancel-summary").textContent).toContain("Вернём 12");

    await waitFor(() => {
      const button = screen.getByTestId("issue-cancel-confirm") as HTMLButtonElement;
      expect(button.disabled).toBe(true);
    });
  });

  it("когда отменять можно — кнопка активна и уходит в `cancelIssue`", async () => {
    vi.mocked(previewIssueCancellation).mockResolvedValue(preview({}));
    vi.mocked(cancelIssue).mockResolvedValue({
      issue_no: "ISSUE-1",
      cancelled_transfers: [{ transfer_id: 10, transfer_no: "T-10", status: "cancelled" }],
      restored_stages: [{ task_id: 99, sequence: 2, stage_name: "Пиление" }],
    });

    mount("ISSUE-1");

    const button = (await screen.findByTestId("issue-cancel-confirm")) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(cancelIssue).toHaveBeenCalled());
  });
});

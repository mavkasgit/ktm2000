import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/actions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/actions")>()),
  previewReverse: vi.fn(),
  reverseAction: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({
  toast: vi.fn(),
}));

import { previewReverse, reverseAction, type PreviewResponse } from "@/shared/api/actions";
import { toast } from "@/shared/ui/use-toast";
import { ReversePreviewDialog } from "./ReversePreviewDialog";
import type { JournalAction } from "@/shared/api/actions";

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
  revert: [{ id: 5, action_type: "transfer_send", ref_id: 11, status: "active", depends_on: [] }],
  stays: [{ id: 9, action_type: "task_complete", ref_id: 12, status: "active", depends_on: [5] }],
  blockers: [],
  plan_token: "tok-1",
  ...overrides,
});

const httpError = (status: number, detail: unknown) => ({
  response: { status, data: { detail } },
});

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReversePreviewDialog
        action={action}
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(previewReverse).mockResolvedValue(makePreview());
});
async function clickConfirmWhenEnabled() {
  await screen.findByTestId("reverse-confirm");
  await waitFor(() => {
    const button = screen.getByTestId("reverse-confirm") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
  fireEvent.click(screen.getByTestId("reverse-confirm"));
}

describe("ReversePreviewDialog", () => {
  it("показывает три зоны предпросмотра 🔴/⚪/🚫", async () => {
    renderDialog();

    await screen.findByTestId("preview-zone-revert");
    expect(screen.getByText("🔴 Отменится (1)")).toBeTruthy();
    expect(screen.getByText("⚪ Останется (1)")).toBeTruthy();
    expect(screen.getByText("🚫 Блокировки (0)")).toBeTruthy();
    expect(previewReverse).toHaveBeenCalledWith(5, false);
  });

  it("подтверждает отмену с plan_token и закрывает диалог", async () => {
    vi.mocked(reverseAction).mockResolvedValue({
      action_id: 5,
      reversal_action_id: 99,
      reversed_action_ids: [5],
      compensated_tx_ids: [1, 2],
    });
    const onOpenChange = vi.fn();
    const onReversed = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ReversePreviewDialog action={action} open onOpenChange={onOpenChange} onReversed={onReversed} />
      </QueryClientProvider>,
    );
    await clickConfirmWhenEnabled();
    await waitFor(() => {
      expect(reverseAction).toHaveBeenCalledWith(5, {
        plan_token: "tok-1",
        reason: null,
      });
    });
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
    expect(onReversed).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Действие отменено" }),
    );
  });

  it("при блокировках подтверждение недоступно и план-токен не запрашивается", async () => {
    vi.mocked(previewReverse).mockResolvedValue(
      makePreview({
        blockers: [
          { kind: "already_reversed", node_id: 5, detail: "Уже отменено доменно", deficit: null, chain: null },
        ],
        plan_token: null,
      }),
    );
    renderDialog();

    await screen.findByTestId("preview-zone-blockers");
    expect(screen.getByText("Уже отменено доменно")).toBeTruthy();

    await waitFor(() => {
      const button = screen.getByTestId("reverse-confirm") as HTMLButtonElement;
      expect(button.disabled).toBe(true);
    });
  });

  it("StalePlanToken → тост «Мир изменился» + авто-refresh предпросмотра", async () => {
    vi.mocked(reverseAction).mockRejectedValue(
      httpError(409, "Мир изменился с момента preview — пересмотрите preview"),
    );
    renderDialog();
    await clickConfirmWhenEnabled();

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: "destructive",
          title: "Мир изменился, предпросмотр обновлён",
        }),
      );
    });
    // preview перезапрошен автоматически после stale-токена
    await waitFor(() => {
      expect(previewReverse).toHaveBeenCalledTimes(2);
    });
    // Диалог не закрыт — пользователь видит обновлённый предпросмотр
    expect(screen.getByTestId("reverse-preview-dialog")).toBeTruthy();
  });

  it("HasDependentActions → предлагает каскад и перезапрашивает preview с cascade=true", async () => {
    vi.mocked(reverseAction).mockRejectedValue(
      httpError(409, {
        error: "Есть зависимые действия, которые нужно отменить первыми: #7",
        chain: [7],
      }),
    );
    renderDialog();
    await clickConfirmWhenEnabled();

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: "destructive",
          title: "Есть зависимые действия",
        }),
      );
    });
    await waitFor(() => {
      expect(previewReverse).toHaveBeenLastCalledWith(5, true);
    });
  });
});

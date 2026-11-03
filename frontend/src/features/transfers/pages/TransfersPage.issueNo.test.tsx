// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IncomingTransfer } from "@/shared/api/transfers";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  listReadyToTransfer: vi.fn(),
  listTransferHistory: vi.fn(),
}));

vi.mock("@/shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

import { getSpgList, type SpgOut } from "@/shared/api/spg";
import { listReadyToTransfer, listTransferHistory } from "@/shared/api/transfers";
import { TransfersPage } from "./TransfersPage";

const spg = (id: number, name: string): SpgOut => ({
  id,
  code: `GP${id}`,
  name,
  description: null,
  sort_order: id,
  is_active: true,
  icon: null,
  icon_color: null,
  sections: [],
});

const transfer = (over: Partial<IncomingTransfer>): IncomingTransfer => ({
  transfer_id: 42,
  transfer_no: "T-42",
  status: "accepted",
  from_task_id: 1,
  to_task_id: 2,
  from_section_id: 1,
  from_section_code: "SAW",
  from_section_name: "Пиление",
  to_section_id: 2,
  to_section_code: "PRESS",
  to_section_name: "Пресс",
  from_operation_name: "Рез",
  to_operation_name: "Штамповка",
  sent_quantity: "12",
  accepted_quantity: "12",
  rejected_quantity: "0",
  remaining_quantity: "0",
  comment: null,
  sent_at: null,
  created_at: null,
  is_post_factum: false,
  physical_handover_at: null,
  from_task_status: "completed",
  to_task_status: "in_progress",
  product_sku: "SKU-1",
  from_line_id: 1,
  from_line_sequence: 1,
  plan_position_id: 7,
  dimensions: null,
  ...over,
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([spg(1, "ГХП №1")]);
  vi.mocked(listReadyToTransfer).mockResolvedValue({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
    filters: { section_id: null, spg_id: null },
  });
});

describe("TransfersPage: журнал передач различает выдачу (#282)", () => {
  it("строка с `issue_no` печатает номер выдачи и даёт вход в отмену выдачи", async () => {
    vi.mocked(listTransferHistory).mockResolvedValue({
      section_id: null,
      spg_id: null,
      transfers: [transfer({ transfer_id: 42, issue_no: "ISSUE-2026" })],
      total: 1,
      limit: 50,
      offset: 0,
    });

    renderPage();
    await waitFor(() => expect(listReadyToTransfer).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /Журнал передач/ }));

    // Номер выдачи и номер передачи видны в журнале.
    expect((await screen.findByTestId("history-issue-no-42")).textContent).toContain("ISSUE-2026");
    expect(screen.getByTestId("history-transfer-no-42").textContent).toContain("T-42");
    // Есть вход «отменить выдачу целиком» именно на этой строке.
    expect(screen.getByTestId("history-cancel-issue-42")).toBeTruthy();
  });

  it("у обычной передачи без `issue_no` входа в отмену выдачи нет", async () => {
    vi.mocked(listTransferHistory).mockResolvedValue({
      section_id: null,
      spg_id: null,
      transfers: [transfer({ transfer_id: 43, issue_no: null })],
      total: 1,
      limit: 50,
      offset: 0,
    });

    renderPage();
    await waitFor(() => expect(listReadyToTransfer).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Журнал передач/ }));

    await screen.findByTestId("history-transfer-no-43");
    expect(screen.queryByTestId("history-issue-no-43")).toBeNull();
    expect(screen.queryByTestId("history-cancel-issue-43")).toBeNull();
  });
});

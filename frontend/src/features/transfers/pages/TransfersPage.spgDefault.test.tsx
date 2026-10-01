import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  vi.mocked(getSpgList).mockResolvedValue([spg(1, "ГХП №1"), spg(2, "ГХП №2")]);
  vi.mocked(listReadyToTransfer).mockImplementation(async (params = {}) => ({
    items: [],
    total: 0,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
    filters: { section_id: null, spg_id: params.spg_id ?? null },
  }));
  vi.mocked(listTransferHistory).mockResolvedValue({
    section_id: null,
    spg_id: null,
    transfers: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
});

describe("TransfersPage: дефолт «Все ГХП»", () => {
  it("открывается на «Все ГХП» и просит данные без spg_id", async () => {
    renderPage();

    await waitFor(() => expect(listReadyToTransfer).toHaveBeenCalled());
    expect(screen.queryByText("Все ГХП")).not.toBeNull();

    const calls = vi.mocked(listReadyToTransfer).mock.calls;
    expect(calls[calls.length - 1]?.[0]?.spg_id).toBeUndefined();
  });

  it("не подставляет данные первой активной ГХП под пустой выбор", async () => {
    renderPage();
    await waitFor(() => expect(listReadyToTransfer).toHaveBeenCalled());

    // Оператор раскрывает селект и берёт пустой пункт «Выберите ГХП»: выбор
    // снимается, и запросы не должны молча уйти по первой активной ГХП.
    fireEvent.click(screen.getByRole("combobox"));
    const emptyOption = await screen.findByRole("option", { name: "Выберите ГХП" });
    fireEvent.click(emptyOption);

    await waitFor(() => expect(screen.getByRole("combobox").textContent).toContain("Выберите ГХП"));

    const ids = vi.mocked(listReadyToTransfer).mock.calls.map((c) => c[0]?.spg_id);
    expect(ids).not.toContain(1);
    expect(ids.every((id) => id === undefined)).toBe(true);
  });
});

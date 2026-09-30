import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/features/auth/hooks/useAuth", () => ({ useAuth: vi.fn() }));

import { useAuth, type AuthShellUser } from "@/features/auth/hooks/useAuth";
import type { JournalAction } from "@/shared/api/actions";
import { JournalRowOperations } from "./JournalRowOperations";

const makeAction = (overrides: Partial<JournalAction> = {}): JournalAction => ({
  id: 1,
  action_type: "transfer_send",
  ref_id: 10,
  actor: "Оператор",
  status: "active",
  depends_on: [],
  created_at: "2026-09-01T10:00:00Z",
  ...overrides,
});

function setUser(role: string | null) {
  const user: AuthShellUser | null = role
    ? { username: "u", full_name: "U", role }
    : null;
  vi.mocked(useAuth).mockReturnValue({
    user,
    rolesCatalog: [],
    roleLabel: (r: string) => r,
    roleSections: () => [],
    isAuthenticated: user !== null,
    isLoading: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  });
}

function renderRow(action: JournalAction) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <JournalRowOperations action={action} onChanged={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("JournalRowOperations — гейт отката импорта остатков", () => {
  it("скрывает «Отменить» у import_remainders для не-админа (ADR-0052 п.6)", () => {
    setUser("viewer");
    renderRow(makeAction({ action_type: "import_remainders" }));

    expect(screen.queryByTestId("reverse-button-1")).toBeNull();
    // Дерево цепочки остаётся: чтение не гейтится.
    expect(screen.getByTestId("tree-button-1")).toBeTruthy();
  });

  it("показывает «Отменить» у import_remainders админу", () => {
    setUser("admin");
    renderRow(makeAction({ action_type: "import_remainders" }));

    const reverse = screen.getByTestId("reverse-button-1") as HTMLButtonElement;
    expect(reverse.disabled).toBe(false);
  });

  it("обычный тип не зависит от роли: кнопка отмены видна зрителю", () => {
    setUser("viewer");
    renderRow(makeAction({ action_type: "task_complete" }));

    const reverse = screen.getByTestId("reverse-button-1") as HTMLButtonElement;
    expect(reverse.disabled).toBe(false);
  });

  it("отменённое действие неактивно и у админа", () => {
    setUser("admin");
    renderRow(makeAction({ status: "reversed" }));

    const reverse = screen.getByTestId("reverse-button-1") as HTMLButtonElement;
    expect(reverse.disabled).toBe(true);
  });
});

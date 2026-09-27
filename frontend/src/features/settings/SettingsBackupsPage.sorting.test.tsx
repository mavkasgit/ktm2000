/**
 * Сортировка списка бэкапов: наружу уходит строка `sort`, а дефолтный
 * порядок «свежие сверху» сохраняется, пока оператор не выбрал другую
 * колонку.
 *
 * Проверка «сортировка нестандартная» для кнопки сброса читает ту же
 * строку, что уходит в запрос: если они разойдутся, кнопка будет врать.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/entities/backup/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/backup/api")>()),
  fetchBackups: vi.fn(),
  fetchBackupConfig: vi.fn(),
  fetchCurrentPreview: vi.fn(),
}));

import { usePermission } from "@/features/auth/hooks/usePermission";
import { fetchBackupConfig, fetchBackups, fetchCurrentPreview } from "@/entities/backup/api";
import { BackupsPage } from "./SettingsBackupsPage";

import type { UsePermissionResult } from "@/features/auth/hooks/usePermission";
import type { BackupPreview } from "@/entities/backup/types";
const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <BackupsPage />
    </QueryClientProvider>,
  );

// У активной колонки в aria-label добавляется направление: «Сортировка по size (desc)».
const clickSort = (field: string) =>
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^Сортировка по ${field}`) }));

/** Строка `sort` последнего запроса списка бэкапов. */
const lastSort = () => {
  const calls = vi.mocked(fetchBackups).mock.calls;
  return calls[calls.length - 1]?.[0]?.sort;
};

const resetButton = () => screen.getByRole("button", { name: "Сбросить фильтры" }) as HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePermission).mockReturnValue({ canEditSettings: true } as UsePermissionResult);
  vi.mocked(fetchBackups).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  vi.mocked(fetchBackupConfig).mockResolvedValue({ db_name: "ktm2000", auto_enabled: false, time_of_day: "23:00" });
  vi.mocked(fetchCurrentPreview).mockResolvedValue(null as unknown as BackupPreview);
});

describe("BackupsPage: сортировка", () => {
  it("до первого клика по шапке просит свежие бэкапы сверху", async () => {
    renderPage();

    await waitFor(() => expect(fetchBackups).toHaveBeenCalled());
    expect(lastSort()).toBe("created_at:desc");
  });

  it("выбор другой колонки уходит в запрос строкой с полем API", async () => {
    renderPage();
    await waitFor(() => expect(lastSort()).toBe("created_at:desc"));

    clickSort("filename");
    await waitFor(() => expect(lastSort()).toBe("filename:asc"));
  });

  it("снятие сортировки возвращает дефолтный порядок", async () => {
    renderPage();
    await waitFor(() => expect(lastSort()).toBe("created_at:desc"));

    // размер: убыв. → возр. → снять → снова дефолтный порядок
    clickSort("size");
    await waitFor(() => expect(lastSort()).toBe("size:desc"));
    clickSort("size");
    await waitFor(() => expect(lastSort()).toBe("size:asc"));
    clickSort("size");
    await waitFor(() => expect(lastSort()).toBe("created_at:desc"));
  });

  it("кнопка сброса возвращает дефолтный порядок", async () => {
    renderPage();
    await waitFor(() => expect(lastSort()).toBe("created_at:desc"));

    clickSort("comment");
    await waitFor(() => expect(lastSort()).toBe("comment:asc"));

    resetButton().click();
    await waitFor(() => expect(lastSort()).toBe("created_at:desc"));
  });
});

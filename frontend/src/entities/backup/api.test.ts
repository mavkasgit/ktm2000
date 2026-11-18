import { beforeEach, describe, expect, it, vi } from "vitest";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { get } }));
vi.mock("@/shared/lib/downloadFile", () => ({ saveBlobAsFile: vi.fn() }));

import { saveBlobAsFile } from "@/shared/lib/downloadFile";

import { downloadBackup } from "./api";

const FILENAME = "backup_ktm2000_test_2026-01-01_10-00-00.zip";

describe("downloadBackup — файл идёт через apiClient (ADR-0052 п.9, #409)", () => {
  beforeEach(() => {
    get.mockReset();
    vi.mocked(saveBlobAsFile).mockReset();
  });

  it("blob-запрос вместо ссылки без заголовка: Authorization едет с запросом", async () => {
    const blob = new Blob(["dump"]);
    get.mockResolvedValue({ data: blob });

    await downloadBackup(FILENAME);

    expect(get).toHaveBeenCalledWith(`/backups/${FILENAME}/download`, {
      responseType: "blob",
    });
    expect(saveBlobAsFile).toHaveBeenCalledWith(blob, FILENAME);
  });

  it("ошибка API не превращается в скачанный файл", async () => {
    get.mockRejectedValue(new Error("401"));

    await expect(downloadBackup(FILENAME)).rejects.toThrow("401");
    expect(saveBlobAsFile).not.toHaveBeenCalled();
  });
});

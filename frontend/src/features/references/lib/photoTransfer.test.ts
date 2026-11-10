import { afterEach, describe, expect, it, vi } from "vitest";

import { saveBlobAsFile } from "@/shared/lib/downloadFile";
import { copyPhoto, downloadPhoto, photoFileName } from "./photoTransfer";

vi.mock("@/shared/lib/downloadFile", () => ({ saveBlobAsFile: vi.fn() }));

function pngBlob(): Blob {
  return new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
}

function stubFetch(blob: Blob) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, blob: async () => blob })),
  );
}

function setClipboardWrite(write: ((items: ClipboardItem[]) => Promise<void>) | null) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: write ? { write } : undefined,
  });
}

class FakeClipboardItem {
  static supports = () => true;
  constructor(public readonly items: Record<string, Blob>) {}
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(saveBlobAsFile).mockReset();
  setClipboardWrite(null);
  Object.defineProperty(document, "execCommand", { configurable: true, value: undefined });
});

describe("photoFileName", () => {
  it("берёт имя файла из URL без версии", () => {
    expect(photoFileName("/static/products/035_206_full.png?v=1a2b-3c4d")).toBe("035_206_full.png");
  });

  it("для blob-адреса подставляет нейтральное имя", () => {
    expect(photoFileName("blob:http://localhost/5f0c-4b2a")).toBe("photo");
  });
});

describe("downloadPhoto", () => {
  it("скачивает фото под его именем", async () => {
    const blob = pngBlob();
    stubFetch(blob);

    const fileName = await downloadPhoto("/static/products/033_205_full.jpg?v=10-20");

    expect(fileName).toBe("033_205_full.jpg");
    expect(saveBlobAsFile).toHaveBeenCalledWith(blob, "033_205_full.jpg");
  });

  it("для blob-адреса достраивает расширение по типу", async () => {
    const blob = pngBlob();
    stubFetch(blob);

    const fileName = await downloadPhoto("blob:http://localhost/5f0c-4b2a");

    expect(fileName).toBe("photo.png");
  });

  it("падает, когда сервер не отдал файл", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 })));

    await expect(downloadPhoto("/static/products/033_205_full.jpg")).rejects.toThrow("404");
    expect(saveBlobAsFile).not.toHaveBeenCalled();
  });
});

describe("copyPhoto", () => {
  it("использует Clipboard API, когда он доступен", async () => {
    const blob = pngBlob();
    stubFetch(blob);
    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    let received: ClipboardItem[] | null = null;
    const write = vi.fn(async (items: ClipboardItem[]) => {
      received = items;
    });
    setClipboardWrite(write);

    await copyPhoto("/static/products/033_205_full.png?v=10-20");

    expect(write).toHaveBeenCalledTimes(1);
    const items = received as unknown as FakeClipboardItem[] | null;
    expect(items?.[0].items["image/png"]).toBe(blob);
  });

  it("на HTTP выделяет картинку и копирует через execCommand", async () => {
    stubFetch(pngBlob());
    vi.stubGlobal("ClipboardItem", undefined);
    setClipboardWrite(null);
    const execCommand = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });

    await copyPhoto("/static/products/033_205_full.png?v=10-20");

    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("бросает ошибку, когда оба пути недоступны", async () => {
    stubFetch(pngBlob());
    vi.stubGlobal("ClipboardItem", undefined);
    setClipboardWrite(null);
    Object.defineProperty(document, "execCommand", { configurable: true, value: vi.fn(() => false) });

    await expect(copyPhoto("/static/products/033_205_full.png")).rejects.toThrow(
      "Браузер не разрешил скопировать изображение",
    );
  });
});

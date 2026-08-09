import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  previewCatalogExcel: vi.fn(),
  applyCatalogExcel: vi.fn(),
  downloadCatalogTemplate: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({
  toast: vi.fn(),
}));

import {
  applyCatalogExcel,
  downloadCatalogTemplate,
  previewCatalogExcel,
  type CatalogPreview,
} from "@/shared/api/products";
import { toast } from "@/shared/ui/use-toast";
import { ImportWizardDialog } from "./ImportWizardDialog";

const makePreview = (overrides: Partial<CatalogPreview> = {}): CatalogPreview => ({
  items: [
    {
      sku: "SKU-CREATE",
      name: "Создаваемый",
      length_mm: 1000,
      quantity_per_hanger: 5,
      has_photo: false,
      action: "create",
    },
  ],
  stats: { total: 1, create: 1, update: 0, skip: 0 },
  ...overrides,
});

const excelFile = (): File =>
  new File(["x"], "catalog.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

const pickFile = (container: HTMLElement) => {
  const file = excelFile();
  const input = container.ownerDocument.querySelector('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [file] } });
  return file;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ImportWizardDialog", () => {
  it("starts on the upload step and switches to the preview step after picking a file", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    const { container } = render(
      <ImportWizardDialog open onOpenChange={vi.fn()} onImported={vi.fn()} />,
    );

    expect(screen.getByRole("heading", { name: "Импорт из Excel" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Скачать шаблон" })).toBeTruthy();

    pickFile(container);

    await screen.findByRole("heading", { name: "Предпросмотр импорта" });
    expect(previewCatalogExcel).toHaveBeenCalledTimes(1);
    // Сводка и таблица предпросмотра из вынесенного компонента
    expect(screen.getByText("1 создать")).toBeTruthy();
    expect(screen.getByText("SKU-CREATE")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Назад" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Импортировать" })).toBeTruthy();
  });

  it("returns to the upload step with «Назад»", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    const { container } = render(
      <ImportWizardDialog open onOpenChange={vi.fn()} onImported={vi.fn()} />,
    );

    pickFile(container);
    await screen.findByRole("heading", { name: "Предпросмотр импорта" });

    fireEvent.click(screen.getByRole("button", { name: "Назад" }));

    expect(screen.getByRole("heading", { name: "Импорт из Excel" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Импортировать" })).toBeNull();
  });

  it("applies the import and moves to the result step on «Импортировать»", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    vi.mocked(applyCatalogExcel).mockResolvedValue({
      imported: 1,
      updated: 0,
      skipped: 0,
      errors: [],
    });
    const onOpenChange = vi.fn();
    const onImported = vi.fn();
    const { container } = render(
      <ImportWizardDialog open onOpenChange={onOpenChange} onImported={onImported} />,
    );

    const file = pickFile(container);
    await screen.findByRole("heading", { name: "Предпросмотр импорта" });

    fireEvent.click(screen.getByRole("button", { name: "Импортировать" }));

    await screen.findByRole("heading", { name: "Результат импорта" });
    expect(applyCatalogExcel).toHaveBeenCalledTimes(1);
    expect(applyCatalogExcel).toHaveBeenCalledWith(file);
    // Список ещё не перезагружается — ждём закрытия результата
    expect(onImported).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByText("Создано: 1")).toBeTruthy();
    expect(screen.getByTestId("import-result-close")).toBeTruthy();
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Импорт завершён" }),
    );
  });

  it("shows the row errors on the result step when some rows are skipped", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    vi.mocked(applyCatalogExcel).mockResolvedValue({
      imported: 1,
      updated: 0,
      skipped: 0,
      errors: [{ row: 7, sku: "SKU-BAD", message: "нет длины" }],
    });
    const { container } = render(
      <ImportWizardDialog open onOpenChange={vi.fn()} onImported={vi.fn()} />,
    );

    pickFile(container);
    await screen.findByRole("heading", { name: "Предпросмотр импорта" });

    fireEvent.click(screen.getByRole("button", { name: "Импортировать" }));

    await screen.findByRole("heading", { name: "Результат импорта" });
    expect(screen.getByText("Ошибки строк (строки пропущены):")).toBeTruthy();
    expect(screen.getByText("Строка 7 — SKU-BAD: нет длины")).toBeTruthy();
  });

  it("closes the dialog and reloads the list on «Закрыть»", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    vi.mocked(applyCatalogExcel).mockResolvedValue({
      imported: 1,
      updated: 0,
      skipped: 0,
      errors: [],
    });
    const onOpenChange = vi.fn();
    const onImported = vi.fn();
    const { container } = render(
      <ImportWizardDialog open onOpenChange={onOpenChange} onImported={onImported} />,
    );

    pickFile(container);
    await screen.findByRole("heading", { name: "Предпросмотр импорта" });

    fireEvent.click(screen.getByRole("button", { name: "Импортировать" }));
    await screen.findByRole("heading", { name: "Результат импорта" });

    fireEvent.click(screen.getByTestId("import-result-close"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("stays on the preview step and toasts when the import fails", async () => {
    vi.mocked(previewCatalogExcel).mockResolvedValue(makePreview());
    vi.mocked(applyCatalogExcel).mockRejectedValue(new Error("network down"));
    const onOpenChange = vi.fn();
    const onImported = vi.fn();
    const { container } = render(
      <ImportWizardDialog open onOpenChange={onOpenChange} onImported={onImported} />,
    );

    pickFile(container);
    await screen.findByRole("heading", { name: "Предпросмотр импорта" });

    fireEvent.click(screen.getByRole("button", { name: "Импортировать" }));

    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "destructive",
        title: "Ошибка импорта: catalog.xlsx",
      }),
    );
    // Остаёмся на предпросмотре, загрузка не зависает — кнопка снова активна
    expect(screen.getByRole("heading", { name: "Предпросмотр импорта" })).toBeTruthy();
    await waitFor(() => {
      const button = screen.getByRole("button", {
        name: "Импортировать",
      }) as HTMLButtonElement;
      expect(button.disabled).toBe(false);
    });
    expect(onImported).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("closes the dialog on «Отмена»", () => {
    const onOpenChange = vi.fn();
    render(<ImportWizardDialog open onOpenChange={onOpenChange} onImported={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("stays on the upload step and toasts when the preview fails to load", async () => {
    vi.mocked(previewCatalogExcel).mockRejectedValue(new Error("bad file"));
    const { container } = render(
      <ImportWizardDialog open onOpenChange={vi.fn()} onImported={vi.fn()} />,
    );

    pickFile(container);

    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "destructive", title: "Ошибка предпросмотра: catalog.xlsx" }),
    );
    expect(screen.getByRole("heading", { name: "Импорт из Excel" })).toBeTruthy();
  });

  it("downloads the template via the API", () => {
    render(<ImportWizardDialog open onOpenChange={vi.fn()} onImported={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Скачать шаблон" }));

    expect(downloadCatalogTemplate).toHaveBeenCalledTimes(1);
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportUploadStep } from "./ImportUploadStep";

describe("ImportUploadStep", () => {
  it("renders the description, the template structure table and the download button", () => {
    render(<ImportUploadStep onFileSelected={vi.fn()} onDownloadTemplate={vi.fn()} />);

    expect(screen.getByText(/Импортируйте справочник сырья из Excel/)).toBeTruthy();
    expect(screen.getByText("Структура шаблона")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Скачать шаблон" })).toBeTruthy();

    // Колонки шаблона справочника сырья
    for (const col of [
      "Артикул",
      "Наименование",
      "Длины, мм",
      "Периметр, мм",
      "Габарит, мм",
      "Кол-во на подвесе",
      "Парный профиль",
      "Не дробеструится",
      "Ламируется",
      "Эквиваленты",
    ]) {
      expect(screen.getByText(col)).toBeTruthy();
    }
  });

  it("calls onDownloadTemplate when the template button is clicked", () => {
    const onDownloadTemplate = vi.fn();
    render(<ImportUploadStep onFileSelected={vi.fn()} onDownloadTemplate={onDownloadTemplate} />);

    fireEvent.click(screen.getByRole("button", { name: "Скачать шаблон" }));

    expect(onDownloadTemplate).toHaveBeenCalledTimes(1);
  });

  it("forwards the selected .xlsx file to onFileSelected", () => {
    const onFileSelected = vi.fn();
    const { container } = render(
      <ImportUploadStep onFileSelected={onFileSelected} onDownloadTemplate={vi.fn()} />,
    );

    const input = container.querySelector('input[type="file"]');
    const file = new File(["x"], "catalog.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    fireEvent.change(input!, { target: { files: [file] } });

    expect(onFileSelected).toHaveBeenCalledTimes(1);
    expect(onFileSelected).toHaveBeenCalledWith(file);
  });

  it("does nothing when the file selection is cancelled (no files)", () => {
    const onFileSelected = vi.fn();
    const { container } = render(
      <ImportUploadStep onFileSelected={onFileSelected} onDownloadTemplate={vi.fn()} />,
    );

    const input = container.querySelector('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [] } });

    expect(onFileSelected).not.toHaveBeenCalled();
  });

  it("rejects a file that is not .xlsx", () => {
    const onFileSelected = vi.fn();
    const { container } = render(
      <ImportUploadStep onFileSelected={onFileSelected} onDownloadTemplate={vi.fn()} />,
    );

    const input = container.querySelector('input[type="file"]')!;
    const file = new File(["x"], "catalog.xls", { type: "application/vnd.ms-excel" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(onFileSelected).not.toHaveBeenCalled();
  });
});

import { useCallback, useRef, useState, type DragEvent } from "react";
import { FileSpreadsheet, Download } from "lucide-react";
import { Button } from "@/shared/ui/button";

const TEMPLATE_COLUMNS = [
  "Артикул",
  "Наименование",
  "Примечания",
  "Длины, мм",
  "Периметр, мм",
  "Габарит, мм",
  "Кол-во на подвесе",
  "Парный профиль",
  "Не дробеструится",
  "Ламируется",
  "Эквиваленты",
];

const EXAMPLE_ROW = [
  "ЮП-1000",
  "Универсальный профиль",
  "—",
  "2780, 6000",
  "—",
  "—",
  "5, 3",
  "Нет",
  "Да",
  "Нет",
  "ЮП-1000А",
];

export function ImportExcelStep({
  onFileSelected,
  onDownloadTemplate,
  loading = false,
}: {
  onFileSelected: (file: File) => void;
  onDownloadTemplate: () => void;
  loading?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      if (!/\.xlsx$/i.test(file.name)) return;
      onFileSelected(file);
    },
    [onFileSelected],
  );

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (loading) return;
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Импортируйте справочник сырья из Excel. Скачайте шаблон, заполните его по
        образцу ниже и загрузите файл — откроется предпросмотр изменений.
      </p>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Структура шаблона</span>
          <Button variant="link" size="sm" onClick={onDownloadTemplate} disabled={loading}>
            <Download className="h-4 w-4 mr-1" />
            Скачать шаблон
          </Button>
        </div>
        <div className="overflow-auto border rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                {TEMPLATE_COLUMNS.map((col) => (
                  <th key={col} className="px-3 py-2 text-left font-medium whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr>
                {EXAMPLE_ROW.map((cell, idx) => (
                  <td key={idx} className="px-3 py-2 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div
        role="button"
        tabIndex={0}
        onClick={() => {
          if (!loading) inputRef.current?.click();
        }}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !loading) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer ${
          dragOver ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"
        } ${loading ? "pointer-events-none opacity-60" : ""}`}
      >
        <FileSpreadsheet className="w-10 h-10 mx-auto text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">Перетащите файл .xlsx сюда</p>
        <p className="text-xs text-muted-foreground">или нажмите для выбора файла</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".xlsx"
        className="hidden"
        disabled={loading}
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

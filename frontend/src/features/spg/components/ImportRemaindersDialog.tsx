import { useState, useRef } from "react";
import { Upload, FileText, Loader2, AlertCircle, CheckCircle } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
} from "@/shared/ui";
import { importRemaindersExcel } from "@/shared/api/spg";

interface ImportRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  onSaved: () => void;
}

export function ImportRemaindersDialog({
  open,
  onOpenChange,
  spgId,
  onSaved,
}: ImportRemaindersDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported_count: number; errors: string[] } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setError(null);
      setResult(null);
    }
  };

  const handleImport = async () => {
    if (!file) return;

    setImporting(true);
    setError(null);
    setResult(null);
    try {
      const response = await importRemaindersExcel(spgId, file);
      if (response.success) {
        setResult({
          imported_count: response.imported_count,
          errors: response.errors,
        });
        onSaved();
      } else {
        setError("Не удалось импортировать данные.");
      }
    } catch (e: any) {
      const msg = e.response?.data?.detail || "Ошибка при импорте Excel-файла";
      setError(msg);
    } finally {
      setImporting(false);
    }
  };

  const handleClose = () => {
    setFile(null);
    setError(null);
    setResult(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Импорт остатков из Excel</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {!result ? (
            <>
              <p className="text-xs text-muted-foreground">
                Загрузите Excel-файл (.xlsx, .xls) для пакетного импорта остатков. 
                В таблице должны быть колонки: <strong className="text-foreground">Артикул</strong> (SKU),{" "}
                <strong className="text-foreground">Количество</strong> (qty), и опционально{" "}
                <strong className="text-foreground">Выполненные операции</strong> (список завершенных стадий через запятую).
              </p>

              {/* Upload Dropzone */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-muted-foreground/30 rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer hover:bg-accent/40 hover:border-primary/50 transition-colors"
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  accept=".xlsx, .xls"
                  className="hidden"
                  disabled={importing}
                />
                
                {file ? (
                  <>
                    <FileText className="h-10 w-10 text-primary mb-2" />
                    <span className="text-sm font-semibold truncate max-w-[280px]">
                      {file.name}
                    </span>
                    <span className="text-xs text-muted-foreground mt-1">
                      {(file.size / 1024).toFixed(1)} KB
                    </span>
                  </>
                ) : (
                  <>
                    <Upload className="h-10 w-10 text-muted-foreground mb-2" />
                    <span className="text-sm font-medium">Выберите файл для загрузки</span>
                    <span className="text-xs text-muted-foreground mt-1">
                      Поддерживаются .xlsx, .xls
                    </span>
                  </>
                )}
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded bg-destructive/10 p-2 text-xs text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button variant="outline" onClick={handleClose} disabled={importing}>
                  Отмена
                </Button>
                <Button onClick={handleImport} disabled={importing || !file}>
                  {importing ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Импорт...
                    </>
                  ) : (
                    "Импортировать"
                  )}
                </Button>
              </div>
            </>
          ) : (
            /* Results Presentation */
            <div className="space-y-4">
              <div className="flex items-center gap-2 rounded bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 p-3 text-sm text-emerald-800 dark:text-emerald-300">
                <CheckCircle className="h-5 w-5 shrink-0 text-emerald-600" />
                <div>
                  <div className="font-semibold">Импорт успешно завершен!</div>
                  <div>Импортировано остатков: {result.imported_count} шт.</div>
                </div>
              </div>

              {result.errors.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Ошибки / Пропущенные строки ({result.errors.length}):
                  </div>
                  <div className="max-h-[160px] overflow-y-auto border rounded bg-destructive/5 dark:bg-destructive/10 p-2 space-y-1">
                    {result.errors.map((err, idx) => (
                      <div key={idx} className="text-xs text-destructive leading-tight border-b pb-1 last:border-0 last:pb-0">
                        {err}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex justify-end pt-2 border-t">
                <Button onClick={handleClose}>Закрыть</Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

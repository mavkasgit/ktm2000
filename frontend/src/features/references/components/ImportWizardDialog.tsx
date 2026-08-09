import { useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
import { Button } from "@/shared/ui/button";
import { toast } from "@/shared/ui/use-toast";
import {
  applyCatalogExcel,
  downloadCatalogTemplate,
  getErrorMessage,
  previewCatalogExcel,
  type CatalogExcelApplyResult,
  type CatalogPreview,
} from "@/shared/api/products";
import { ImportExcelStep } from "./ImportExcelStep";
import { ImportPreviewContent } from "./ImportPreviewContent";
import { ImportResultStep } from "./ImportResultStep";

type Step = "upload" | "preview" | "result";

export function ImportWizardDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
}) {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [result, setResult] = useState<CatalogExcelApplyResult | null>(null);
  const [loading, setLoading] = useState(false);
  // Инвалидирует незавершённые запросы при сбросе (закрытие/повторное открытие).
  const requestIdRef = useRef(0);

  const reset = () => {
    requestIdRef.current += 1;
    setStep("upload");
    setFile(null);
    setPreview(null);
    setResult(null);
    setLoading(false);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      if (result) onImported();
      reset();
    }
    onOpenChange(next);
  };

  const handleFileSelected = async (selected: File) => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    try {
      const result = await previewCatalogExcel(selected);
      if (requestId !== requestIdRef.current) return;
      setFile(selected);
      setPreview(result);
      setStep("preview");
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      toast({
        variant: "destructive",
        title: `Ошибка предпросмотра: ${selected.name}`,
        description: getErrorMessage(err),
      });
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      await downloadCatalogTemplate();
    } catch (err) {
      toast({
        variant: "destructive",
        title: "Ошибка скачивания шаблона",
        description: getErrorMessage(err),
      });
    }
  };

  const handleImport = async () => {
    if (!file) return;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    try {
      const applyResult = await applyCatalogExcel(file);
      if (requestId !== requestIdRef.current) {
        // Диалог закрыт/сброшен во время apply — сервер уже применил импорт,
        // поэтому список перезагружаем, но UI-состояние не трогаем.
        onImported();
        return;
      }
      setResult(applyResult);
      setStep("result");
      const errorsNote = applyResult.errors.length > 0 ? `, с ошибками: ${applyResult.errors.length}` : "";
      toast({
        variant: "success",
        title: "Импорт завершён",
        description: `Файл: "${file.name}". Создано: ${applyResult.imported}, обновлено: ${applyResult.updated}, пропущено: ${applyResult.skipped}${errorsNote}`,
      });
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      toast({
        variant: "destructive",
        title: `Ошибка импорта: ${file.name}`,
        description: getErrorMessage(err),
      });
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  };

  const handleCloseResult = () => {
    handleOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {step === "upload"
              ? "Импорт из Excel"
              : step === "preview"
                ? "Предпросмотр импорта"
                : "Результат импорта"}
          </DialogTitle>
        </DialogHeader>

        {step === "upload" ? (
          <>
            <ImportExcelStep
              onFileSelected={handleFileSelected}
              onDownloadTemplate={handleDownloadTemplate}
              loading={loading}
            />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={loading}>
                Отмена
              </Button>
            </div>
          </>
        ) : step === "preview" && preview ? (
          <>
            <ImportPreviewContent preview={preview} />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setStep("upload")} disabled={loading}>
                Назад
              </Button>
              <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={loading}>
                Отмена
              </Button>
              <Button onClick={handleImport} disabled={loading}>
                Импортировать
              </Button>
            </div>
          </>
        ) : result ? (
          <>
            <ImportResultStep result={result} />
            <div className="flex justify-end gap-2 pt-2">
              <Button data-testid="import-result-close" onClick={handleCloseResult}>
                Закрыть
              </Button>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

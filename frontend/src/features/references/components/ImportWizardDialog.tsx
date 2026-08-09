import { useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
import { Button } from "@/shared/ui/button";
import { toast } from "@/shared/ui/use-toast";
import {
  applyCatalogExcel,
  downloadCatalogTemplate,
  getErrorMessage,
  previewCatalogExcel,
  type CatalogPreview,
} from "@/shared/api/products";
import { ImportUploadStep } from "./ImportUploadStep";
import { ImportPreviewContent } from "./ImportPreviewContent";

type Step = "upload" | "preview";

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
  const [loading, setLoading] = useState(false);
  // Инвалидирует незавершённые запросы при сбросе (закрытие/повторное открытие).
  const requestIdRef = useRef(0);

  const reset = () => {
    requestIdRef.current += 1;
    setStep("upload");
    setFile(null);
    setPreview(null);
    setLoading(false);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
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
    setLoading(true);
    try {
      const result = await applyCatalogExcel(file);
      const errorsNote = result.errors.length > 0 ? `, с ошибками: ${result.errors.length}` : "";
      toast({
        variant: "success",
        title: "Импорт завершён",
        description: `Файл: "${file.name}". Создано: ${result.imported}, обновлено: ${result.updated}, пропущено: ${result.skipped}${errorsNote}`,
      });
      handleOpenChange(false);
      onImported();
    } catch (err) {
      toast({
        variant: "destructive",
        title: `Ошибка импорта: ${file.name}`,
        description: getErrorMessage(err),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{step === "upload" ? "Импорт из Excel" : "Предпросмотр импорта"}</DialogTitle>
        </DialogHeader>

        {step === "upload" ? (
          <>
            <ImportUploadStep
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
        ) : preview ? (
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
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

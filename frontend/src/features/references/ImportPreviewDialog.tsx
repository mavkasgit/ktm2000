import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
import { Button } from "@/shared/ui/button";
import type { CatalogPreview } from "@/shared/api/products";
import { ImportPreviewContent } from "./components/ImportPreviewContent";

export function ImportPreviewDialog({
  open,
  onOpenChange,
  preview,
  loading,
  onImport,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: CatalogPreview | null;
  loading: boolean;
  onImport: () => void;
}) {
  if (!preview) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>Предпросмотр импорта</DialogTitle>
        </DialogHeader>

        <ImportPreviewContent preview={preview} />

        {/* Footer */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button onClick={onImport} disabled={loading}>
            Импортировать
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

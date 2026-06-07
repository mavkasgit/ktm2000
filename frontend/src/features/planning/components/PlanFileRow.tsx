import { useState } from "react"
import { Download, Eye, FileSpreadsheet, Trash2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button, Badge, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { apiClient } from "@/shared/api/client"
import { PlanFileInfo, PlanSummary } from "@/shared/api/productionPlans"
import { getImportFileDownloadUrl } from "@/shared/api/imports"
import { statusLabels, statusVariant } from "../lib/plan-labels"
import { queryKeys } from "@/shared/api/queryKeys"

export function FileRow({ file, activePlan, onDelete }: { file: PlanFileInfo; activePlan: PlanSummary; onDelete: (batchId: number) => void }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const downloadUrl = getImportFileDownloadUrl(file.file_id)

  const { data: previewData } = useQuery({
    queryKey: queryKeys.plan.batchPreview(file.batch_id),
    queryFn: () =>
      apiClient.get(`/production-plans/${activePlan!.id}/batches/${file.batch_id}/preview`).then(r => r.data),
    enabled: previewOpen && !!activePlan,
  })

  const previewItems = ((previewData as any)?.items as Record<string, any>[] | undefined) ?? []

  return (
    <>
      <tr className="border-b">
        <td className="p-3">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">{file.filename}</span>
          </div>
        </td>
        <td className="p-3 text-sm text-muted-foreground">
          {new Date(file.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}
        </td>
        <td className="p-3 text-sm text-muted-foreground">{file.sheet_name}</td>
        <td className="p-3 text-sm">{file.total_rows}</td>
        <td className="p-3 text-sm">
          {(file.size_bytes / 1024).toFixed(1)} KB
        </td>
        <td className="p-3">
          <Badge variant={statusVariant[file.status] as any || "secondary"}>
            {statusLabels[file.status] || file.status}
          </Badge>
        </td>
        <td className="p-3">
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setPreviewOpen(true)}>
              <Eye className="h-3 w-3 mr-1" /> Просмотр
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
              <a href={downloadUrl} download={file.filename}>
                <Download className="h-3 w-3 mr-1" /> Скачать
              </a>
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => setDeleteDialogOpen(true)}>
              <Trash2 className="h-3 w-3 mr-1" /> Удалить
            </Button>
          </div>
        </td>
      </tr>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-[90vw] max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>Файл: {file.filename}</DialogTitle>
            <DialogDescription>Предпросмотр содержимого загруженного файла</DialogDescription>
          </DialogHeader>
          {previewItems.length === 0 && (
            <p className="text-sm text-muted-foreground">Предпросмотр недоступен</p>
          )}
          {previewItems.length > 0 && (
            <div className="flex-1 overflow-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className="text-left p-2">Артикул</th>
                    <th className="text-left p-2">Наименование</th>
                    <th className="text-left p-2">Кол-во</th>
                    <th className="text-left p-2">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {previewItems.slice(0, 100).map((row, i) => (
                    <tr key={i} className="border-b">
                      <td className="p-2">{row.source_sku ?? row.sku ?? "—"}</td>
                      <td className="p-2">{row.source_name ?? row.product_name ?? "—"}</td>
                      <td className="p-2">{row.quantity ?? "—"}</td>
                      <td className="p-2">{row.status ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {previewItems.length > 100 && (
                <p className="text-xs text-muted-foreground p-2">Показано 100 из {previewItems.length} строк</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить импорт?</AlertDialogTitle>
            <AlertDialogDescription>
              Файл «{file.filename}» и все связанные позиции будут удалены. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={() => onDelete(file.batch_id)}>Удалить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

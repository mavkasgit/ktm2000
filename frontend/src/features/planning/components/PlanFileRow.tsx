import { Fragment, useState } from "react"
import { Download, Eye, FileSpreadsheet, Trash2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button, Badge, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { PlanFileInfo, PlanSummary } from "@/shared/api/productionPlans"
import {
  fetchAllImportBatchItems,
  fetchImportItem,
  getImportFileDownloadUrl,
  type ImportFullItem,
} from "@/shared/api/imports"
import { statusLabels, statusVariant } from "../lib/plan-labels"
import { isDuplicateRow } from "../lib/duplicateRows"
import { queryKeys } from "@/shared/api/queryKeys"

export function FileRow({ file, activePlan, onDelete }: { file: PlanFileInfo; activePlan: PlanSummary; onDelete: (batchId: number) => void }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null)
  const downloadUrl = getImportFileDownloadUrl(file.file_id)

  const { data: lightRows, isLoading: rowsLoading } = useQuery({
    queryKey: [...queryKeys.plan.batchPreview(file.batch_id), "light"],
    queryFn: () => fetchAllImportBatchItems(file.batch_id),
    enabled: previewOpen && !!activePlan,
  })
  const previewItems = lightRows ?? []

  const { data: fullItem, isLoading: fullLoading } = useQuery({
    queryKey: [...queryKeys.plan.batchPreview(file.batch_id), "item", selectedItemId],
    queryFn: () => fetchImportItem(selectedItemId as number, true) as Promise<ImportFullItem>,
    enabled: previewOpen && selectedItemId != null,
  })

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
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => { setSelectedItemId(null); setPreviewOpen(true) }}>
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
            <DialogDescription>Лёгкие строки батча; детали строки подгружаются по клику</DialogDescription>
          </DialogHeader>
          {rowsLoading && (
            <p className="text-sm text-muted-foreground">Загрузка строк…</p>
          )}
          {!rowsLoading && previewItems.length === 0 && (
            <p className="text-sm text-muted-foreground">Предпросмотр недоступен</p>
          )}
          {previewItems.length > 0 && (
            <div className="flex-1 overflow-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className="text-left p-2">Строки</th>
                    <th className="text-left p-2">Артикул</th>
                    <th className="text-left p-2">Наименование</th>
                    <th className="text-left p-2">Кол-во</th>
                    <th className="text-left p-2">Статус</th>
                    <th className="text-left p-2">Действие</th>
                  </tr>
                </thead>
                <tbody>
                  {previewItems.map((row) => (
                    <Fragment key={row.item_id}>
                      <tr
                        className="border-b cursor-pointer hover:bg-muted/40"
                        onClick={() => setSelectedItemId((prev) => (prev === row.item_id ? null : row.item_id))}
                      >
                        <td className="p-2">{row.source_row_numbers.join(", ") || "—"}</td>
                        <td className="p-2">{row.source_sku ?? "—"}</td>
                        <td className="p-2">{row.source_name ?? "—"}</td>
                        <td className="p-2">{row.quantity ?? "—"}</td>
                        <td className="p-2">
                          <span className="mr-1">{row.status}</span>
                          {isDuplicateRow(row) && (
                            <Badge variant="outline" className="text-violet-700 border-violet-200 bg-violet-50">Дубль</Badge>
                          )}
                        </td>
                        <td className="p-2">{row.change_action}</td>
                      </tr>
                      {selectedItemId === row.item_id && (
                        <tr key={`${row.item_id}-detail`} className="border-b bg-muted/30">
                          <td className="p-2" colSpan={6}>
                            {fullLoading && <span className="text-xs text-muted-foreground">Загрузка деталей…</span>}
                            {!fullLoading && fullItem && <ItemDetail item={fullItem} />}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
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
            <AlertDialogAction
              onClick={() => onDelete(file.batch_id)}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function ItemDetail({ item }: { item: ImportFullItem }) {
  const after = item.after_data ?? {}
  const fields: [string, unknown][] = [
    ["Артикул", after.source_sku],
    ["Наименование", after.source_name],
    ["Количество", after.quantity],
    ["Маршрут", after.route_name],
    ["Действие", item.change_action],
    ["Статус", item.status],
  ]
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap gap-1">
        {[...item.errors, ...item.warnings].map((code) => (
          <Badge key={code} variant="outline" className="font-normal">{code}</Badge>
        ))}
        {item.errors.length === 0 && item.warnings.length === 0 && (
          <span className="text-muted-foreground">Без ошибок и предупреждений</span>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
        {fields.map(([label, value]) => (
          <div key={label} className="flex gap-2">
            <dt className="text-muted-foreground">{label}:</dt>
            <dd className="font-medium">{value == null || value === "" ? "—" : String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

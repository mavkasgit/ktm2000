import { useQuery } from "@tanstack/react-query"

import { allPlanFiles } from "@/shared/api/productionPlans"
import type { ImportApplyStats } from "@/shared/api/imports"
import { queryKeys } from "@/shared/api/queryKeys"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@/shared/ui"

import { findNewerAppliedBatch } from "../lib/appliedBatches"
import { PLAN_IMPORT_ERROR_LABELS } from "./PlanImportPreviewTable"

/**
 * Подтверждение применения импорта плана (#172): общий диалог визарда и строки
 * файла в списке. Состав идентичен спека-диалогу §4.3: цифры по статусам,
 * карточка файла/листа, красный блок ошибок с человеческими подписями и выбор
 * «Загрузить с ошибками» / «Загрузить без ошибок».
 */
export function ApplyImportConfirmDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  stats: ImportApplyStats
  filename: string
  sheetName: string
  /** Строка «Строки: …» в карточке файла; undefined — не показывать. */
  rowsLabel?: string
  planId: number | null
  batchId: number | null
  /** Момент парсинга батча — база для предупреждения о свежести (§4.4). */
  parsedAt: string | null
  loading?: boolean
  onConfirm: (skipInvalid: boolean) => void
  onCancel: () => void
}) {
  const { stats, filename, sheetName, rowsLabel, planId, batchId, parsedAt, loading } = props

  const { data: files } = useQuery({
    queryKey: queryKeys.plan.allFiles(),
    queryFn: () => allPlanFiles(),
    enabled: props.open && planId != null && batchId != null && parsedAt != null,
  })

  // Свежесть не блокирует: предупреждаем, если после парсинга этого батча
  // применялся другой батч того же плана.
  const newerBatch = findNewerAppliedBatch(files ?? [], { planId, batchId, parsedAt })
  const errorBreakdownEntries = Object.entries(stats.errors).sort((a, b) => b[1] - a[1])

  return (
    <AlertDialog open={props.open} onOpenChange={props.onOpenChange}>
      <AlertDialogContent className="max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>Подтвердите применение</AlertDialogTitle>
          <div className="mt-2 space-y-3 text-sm">
            <dl className="divide-y overflow-hidden rounded-lg border">
              <div className="flex items-center justify-between gap-4 px-3 py-1.5">
                <dt>Всего строк</dt>
                <dd className="font-semibold tabular-nums">{stats.total}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 bg-green-50 px-3 py-1.5">
                <dt>Новые</dt>
                <dd className="font-semibold tabular-nums text-green-700">{stats.normal}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 bg-amber-50 px-3 py-1.5">
                <dt>С предупреждениями</dt>
                <dd className="font-semibold tabular-nums text-amber-700">{stats.warning}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 bg-red-50 px-3 py-1.5">
                <dt>С ошибками</dt>
                <dd className="font-semibold tabular-nums text-red-700">{stats.invalid}</dd>
              </div>
              {stats.duplicates > 0 && (
                <div
                  className="flex items-center justify-between gap-4 bg-violet-50 px-3 py-1.5"
                  title="Дубликаты входят в предупреждения или ошибки — это не отдельная категория"
                >
                  <dt>В том числе дубликаты</dt>
                  <dd className="font-semibold tabular-nums text-violet-700">{stats.duplicates}</dd>
                </div>
              )}
            </dl>
            <div className="rounded border p-2">
              <div className="text-muted-foreground">Файл</div>
              <div className="font-medium break-all">{filename || "—"}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                Лист: {sheetName || "—"}
                {rowsLabel ? `; ${rowsLabel}` : ""}
              </div>
            </div>
            {newerBatch && (
              <div className="rounded border border-amber-200 bg-amber-50 p-3 text-amber-900">
                После распознавания этого файла применялся другой импорт плана «{newerBatch.filename}». Строки
                распознаны по состоянию плана на тот момент — проверьте дубликаты и конфликты перед загрузкой.
              </div>
            )}
            {stats.invalid > 0 && (
              <div className="rounded border border-red-200 bg-red-50 p-3">
                <div className="font-medium text-red-900 mb-2">Ошибки в {stats.invalid} строках:</div>
                <div className="space-y-1 max-h-40 overflow-y-auto text-xs">
                  {errorBreakdownEntries.map(([error, count]) => (
                    <div key={error} className="flex items-start gap-2 text-red-800">
                      <span className="text-red-600 mt-0.5">•</span>
                      <span className="font-medium">{PLAN_IMPORT_ERROR_LABELS[error] ?? error}</span>
                      <span className="text-red-600 ml-auto">{count} строк</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 pt-2 border-t border-red-200">
                  <AlertDialogDescription className="text-red-700">
                    Кнопка «Загрузить без ошибок» загрузит только строки без ошибок, невалидные будут пропущены.
                  </AlertDialogDescription>
                </div>
              </div>
            )}
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={props.onCancel}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => props.onConfirm(false)} disabled={loading}>
            {stats.invalid > 0 ? `Загрузить с ошибками (${stats.uploadAll} строк)` : `Загрузить (${stats.uploadAll} строк)`}
          </AlertDialogAction>
          {stats.invalid > 0 && (
            <Button variant="success" onClick={() => props.onConfirm(true)} disabled={loading}>
              Загрузить без ошибок ({stats.uploadSkipInvalid} строк)
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

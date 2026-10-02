/**
 * ReadyTransferPrintDialog.tsx — лист печати очереди «Готово к передаче».
 *
 * Печатается то же, что видит оператор: загруженная выборка (поиск, фильтры и
 * порядок колонки уже применены сервером) теми же шестью колонками, что и
 * таблица. Значение ячейки берётся тем же правилом, что и на экране
 * (`getReadyCellValue`), — напечатанное и показанное не расходятся.
 *
 * Механика печати общая с планом участка: правила — в `PrintStyles`, окно
 * помечает себя `print-area`, лист — `print-sheet`, служебная шапка —
 * `no-print` (см. `shared/ui/PrintSheet.tsx`). Ширина листа в окне тоже
 * общая (`PRINT_SHEET_WIDTH_CLASS`), а таблица ширится по содержимому от
 * центра листа. На печати она остаётся такой же, как в превью: `fit-table`
 * отменяет для неё растяжку листа, колонки не раздвигаются.
 */
import { Printer } from "lucide-react";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  PRINT_SHEET_WIDTH_CLASS,
  PrintStyles,
} from "@/shared/ui";
import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { cn } from "@/shared/utils/cn";

import { getReadyCellValue, readyColumns, type ReadyColumn } from "../lib/transferColumns";
import { nextStepLabel, readyRowIdentity } from "../lib/groupReadyTransfers";

/**
 * Колонки листа: на бумаге ID строки не нужен — оператор ищет по артикулу,
 * размеру и адресату, а `plan_position_id` на листе только шумит.
 */
const printColumns: ReadyColumn[] = readyColumns.filter((column) => column.id !== "positionId");

/**
 * Значение ячейки листа. Отличие от экрана одно: у колонки «Следующий» на экране
 * печатается подпись адресата без кода участка (`nextStepLabel`), а в общем
 * правиле ячейки код есть — он нужен фильтру (`splitNext` разбирает «операция /
 * код»). На бумаге код латиницей («/ WIP_STOCK») читается как мусор, поэтому
 * лист берёт ту же подпись, что экран.
 */
function printCellValue(row: ReadyToTransferTask, column: ReadyColumn): string {
  if (column.id === "next") {
    return row.has_next_step
      ? nextStepLabel(row.next_operation_name, row.next_section_name)
      : "Финальный";
  }
  return column.sortField ? getReadyCellValue(row, column.sortField) : "—";
}

export type ReadyTransferPrintDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Строки выборки в том порядке, в каком их отдал сервер. */
  rows: ReadyToTransferTask[];
  /** Что печатается: «Все ГХП» или название выбранной ГХП. */
  scopeLabel: string;
};

export function ReadyTransferPrintDialog({
  open,
  onOpenChange,
  rows,
  scopeLabel,
}: ReadyTransferPrintDialogProps) {
  const totalQty = rows.reduce((sum, row) => sum + (parseFloat(row.transferable_quantity) || 0), 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <PrintStyles />
      <DialogContent
        className={cn(
          DIALOG_SIZES.wide.width,
          DIALOG_SIZES.wide.height,
          "flex flex-col gap-0 overflow-hidden p-0",
          "bg-white print-area",
        )}
      >
        <DialogHeader className="space-y-1 border-b p-4 text-left no-print">
          <DialogTitle className="text-lg font-semibold">Печать: готово к передаче</DialogTitle>
          <p className="text-xs text-muted-foreground">
            {scopeLabel} · записей {rows.length} · к передаче {fmtQty(totalQty)} шт. —
            печатается текущая выборка (поиск, фильтры и порядок колонки).
          </p>
        </DialogHeader>

        <div className="flex-1 overflow-auto p-4 print-sheet">
          <div className={PRINT_SHEET_WIDTH_CLASS}>
            <div className="mb-4 text-center">
              <div className="text-sm font-bold uppercase tracking-wide">Готово к передаче</div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                {scopeLabel} · сформировано: {new Date().toLocaleString("ru-RU")}
              </div>
            </div>

            {/* Как у плана участка: ширина от содержимого, растёт от центра
                листа. `fit-table` держит колонки в ширину превью и на
                печати — лист не раздвигает их на всю страницу. */}
            <div className="mx-auto w-fit max-w-full rounded-lg border overflow-x-auto">
              <table className="fit-table text-xs border-collapse">
                <thead className="bg-gray-50">
                  <tr className="border-b">
                    {printColumns.map((column) => (
                      <th
                        key={column.id}
                        className={cn(
                          "px-2 py-1 text-left align-middle font-medium text-muted-foreground",
                          column.id === "transferableQty" && "text-right",
                        )}
                      >
                        {column.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={readyRowIdentity(row)} className="border-b">
                      {printColumns.map((column) => (
                        <td
                          key={column.id}
                          className={cn(
                            "px-2 py-1 align-middle",
                            column.id === "transferableQty" && "text-right tabular-nums",
                          )}
                        >
                          {printCellValue(row, column)}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={printColumns.length} className="p-4 text-center text-muted-foreground">
                        Нет заданий, готовых к передаче.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t p-4 no-print">
          <span className="mr-auto text-xs text-muted-foreground">Всего записей: {rows.length}</span>
          <Button type="button" size="sm" variant="ghost" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
          <Button type="button" size="sm" className="gap-2 px-6" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            Печать
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

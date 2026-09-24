/**
 * components/PlanPrintPreviewModal.tsx
 * ======================================
 * Финальный шаг печати плана: превью + кнопка «Печать».
 *
 * Все настройки (фильтры колонок, подвесы, мин/макс количество, заголовок,
 * таблицы) задаются в PlanModal и передаются пропом `settings`.
 * Здесь ничего не настраивается — только предпросмотр и печать.
 *
 * Использует Radix Dialog (через portal в body) — как в hrms PrintPreviewDialog.
 * При печати CSS @media print скрывает всё кроме .print-preview-sheet,
 * что автоматически убирает браузерные колонтитулы.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { PlanTaskTable } from "./PlanTaskTable";
import type { PlanTaskGroupingMode } from "../lib/planTaskGroups";

// ---------------------------------------------------------------------------
// Типы (реэкспорт из PlanModal для удобства импорта)
// ---------------------------------------------------------------------------

export type TableMode = "before" | "after" | "both";

export type PrintColumn =
  | "productSku"
  | "operationName"
  | "dimensions"
  | "qtyPlan"
  | "qtyRemaining"
  | "qtyTransferred"
  | "qtyBalance";

export interface PrintSettings {
  tableMode: TableMode;
  columns: PrintColumn[];
  title: string;
  showQtyPerHanger: boolean;
  minQty: number | null;
  maxQty: number | null;
}

export const ALL_PRINT_COLUMNS: PrintColumn[] = [
  "productSku",
  "operationName",
  "dimensions",
  "qtyPlan",
  "qtyRemaining",
  "qtyTransferred",
  "qtyBalance",
];

export { printColumnLabels as PRINT_COLUMN_LABELS } from "@/shared/lib/generated-labels";


// ---------------------------------------------------------------------------
// PlanPrintPreviewModal (Radix Dialog)
// ---------------------------------------------------------------------------

interface PlanPrintPreviewModalProps {
  sectionName: string;
  onClose: () => void;
  tasks: SectionBoardTask[];
  settings: PrintSettings;
  groupingMode: PlanTaskGroupingMode;
  hiddenGroupKeys: Set<string>;
}

export function PlanPrintPreviewModal({
  sectionName,
  onClose,
  tasks,
  settings,
  groupingMode,
  hiddenGroupKeys,
}: PlanPrintPreviewModalProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  const title =
    settings.title ||
    `План: ${sectionName} от ${new Date().toLocaleDateString("ru-RU")}`;

  function handlePrint() {
    window.print();
  }

  const printContent = tasks.length > 0;

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const hasContent = printContent;
  const [pageCount, setPageCount] = useState(1);

  useLayoutEffect(() => {
    const element = contentRef.current;
    if (!element || !printContent) {
      setPageCount(1);
      return;
    }
    requestAnimationFrame(() => {
      const height = element.scrollHeight;
      setPageCount(Math.max(1, Math.ceil(height / 990)));
    });
  }, [printContent, tasks, title]);





  return (
    <RadixDialog.Root open onOpenChange={() => onClose()}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[60] bg-black/50" />
        <RadixDialog.Content id="print-preview-sheet" className="print-preview-sheet fixed left-[50%] top-[50%] z-[60] w-[90vw] max-w-[1200px] max-h-[90vh] translate-x-[-50%] translate-y-[-50%] bg-white shadow-lg rounded-lg overflow-hidden flex flex-col p-0">
          {/* Print styles — как в hrms */}
          <style>{`
            @page { size: A4 portrait; margin: 0; }
            @media print {
              html, body {
                margin: 0 !important; padding: 0 !important; background: white !important;
                height: auto !important; min-height: auto !important; overflow: visible !important;
              }
              /* Сначала скрываем всё */
              body * { visibility: hidden !important; }
              /* Потом показываем только наш print-preview-sheet и всё внутри */
              #print-preview-sheet, #print-preview-sheet * { visibility: visible !important; }
              /* Прячем всё, что НЕ print-preview-sheet и НЕ focus-guard (overlay, остальной UI) */
              body > *:not(#print-preview-sheet):not([data-radix-focus-guard]) {
                display: none !important;
              }
              /* Растягиваем print-preview-sheet на всю страницу, начиная с (0,0) */
              #print-preview-sheet {
                position: absolute !important;
                left: 0 !important;
                top: 0 !important;
                right: 0 !important;
                bottom: auto !important;
                transform: none !important;
                width: 100% !important;
                max-width: none !important;
                height: auto !important;
                max-height: none !important;
                min-height: auto !important;
                margin: 0 !important;
                padding: 0 !important;
                background: white !important;
                border: none !important;
                border-radius: 0 !important;
                box-shadow: none !important;
                overflow: visible !important;
                display: block !important;
              }
              .no-print { display: none !important; }
              #print-preview-sheet button, #print-preview-sheet [role="button"] { display: none !important; }
              .print-page { page-break-after: always; position: relative; padding: 10mm 15mm; box-sizing: border-box; min-height: 297mm; }
              .print-page:last-child { page-break-after: auto; }
              .print-lines { font-size: 14px; line-height: 1.5; word-break: break-word; overflow-wrap: anywhere; }
              .print-lines > div { border-bottom: 0.5px solid #ccc; padding-bottom: 1px; margin-bottom: 1px; page-break-inside: avoid; }
              .print-header { margin-bottom: 4px; text-align: center; }
              .print-header span { display: inline; font-size: 11px; margin: 0; padding: 0; }
            }
          `}</style>

          {/* Header — финальный шаг: превью + кнопка Печать */}
          <div className="flex items-center justify-between p-4 border-b no-print">
            <div>
              <h2 className="text-lg font-semibold">Печать плана</h2>
              <p className="text-sm text-muted-foreground">{sectionName}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 text-sm font-medium"
                onClick={handlePrint}
              >
                Печать
              </button>
              <kbd className="hidden sm:inline-block text-[10px] text-muted-foreground border rounded px-1.5 py-0.5 font-mono">ESC</kbd>
              <RadixDialog.Close
                className="text-muted-foreground hover:text-foreground text-2xl leading-none"
                aria-label="Закрыть"
              >
                ×
              </RadixDialog.Close>
            </div>
          </div>

          {/* Preview — контент рендерится напрямую, без скрытого measurement */}
          <div className="flex-1 overflow-auto bg-white">
            <div
              ref={contentRef}
              className="mx-auto"
              style={{ width: "210mm", padding: "10mm 15mm" }}
            >
              <div className="print-page bg-white relative">
                <div className="text-center mb-4">
                  <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center justify-center gap-2">
                    <span>Сформировано: {new Date().toLocaleString("ru-RU")}</span>
                    {hasContent && (
                      <span className="text-blue-600 font-medium">· 1/{pageCount}</span>
                    )}
                  </div>
                </div>
                {hasContent ? (
                  <PlanTaskTable
                    tasks={tasks}
                    mode={groupingMode}
                    hiddenGroupKeys={hiddenGroupKeys}
                    onHideGroup={() => undefined}
                    printMode
                  />
                ) : (
                  <p className="text-center text-muted-foreground py-8 text-sm">
                    Нет данных для печати
                  </p>
                )}
              </div>
            </div>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

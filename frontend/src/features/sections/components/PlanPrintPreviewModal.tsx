/**
 * components/PlanPrintPreviewModal.tsx
 * ======================================
 * Модальное окно настройки параметров печати плана с живым превью.
 *
 * Использует Radix Dialog (через portal в body) — как в hrms PrintPreviewDialog.
 * При печати CSS @media print скрывает всё кроме .print-preview-sheet,
 * что автоматически убирает браузерные колонтитулы.
 *
 * Настройки сохраняются в localStorage
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import type { SectionBoardTask, RouteHistoryOp } from "@/shared/api/shopfloor";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { groupTasksByProfile } from "../lib/groupTasksByProfile";
import {
  getQtyPerHanger,
  getPairedHangerLabel,
  adjustQtyToHanger,
} from "./PlanHangerDisplay";

// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

export type TableMode = "before" | "after" | "both";

export interface PrintSettings {
  tableMode: TableMode;
  columns: PrintColumn[];
  title: string;
  showQtyPerHanger: boolean;
  minQty: number | null;
  maxQty: number | null;
}

export type PrintColumn =
  | "productSku"
  | "operationName"
  | "qtyPlan"
  | "qtyRemaining"
  | "qtyTransferred"
  | "qtyBalance";

export const ALL_PRINT_COLUMNS: PrintColumn[] = [
  "productSku",
  "operationName",
  "qtyPlan",
  "qtyRemaining",
  "qtyTransferred",
  "qtyBalance",
];

export const PRINT_COLUMN_LABELS: Record<PrintColumn, string> = {
  productSku: "Артикул",
  operationName: "Операция",
  qtyPlan: "План",
  qtyRemaining: "Осталось выдать",
  qtyTransferred: "Передано",
  qtyBalance: "Остаток",
};

const DEFAULT_SETTINGS: PrintSettings = {
  tableMode: "both",
  columns: ALL_PRINT_COLUMNS,
  title: "",
  showQtyPerHanger: false,
  minQty: null,
  maxQty: null,
};

function loadSettings(sectionId: number): PrintSettings {
  try {
    const raw = localStorage.getItem(`plan-print-settings-${sectionId}`);
    if (raw) {
      const parsed = JSON.parse(raw) as PrintSettings;
      if (parsed.tableMode && Array.isArray(parsed.columns)) {
        return parsed;
      }
    }
  } catch {}
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(sectionId: number, settings: PrintSettings) {
  try {
    localStorage.setItem(
      `plan-print-settings-${sectionId}`,
      JSON.stringify(settings),
    );
  } catch {}
}

// ---------------------------------------------------------------------------
// ToggleButton
// ---------------------------------------------------------------------------

interface ToggleButtonProps {
  label: string;
  active: boolean;
  onClick: () => void;
  size?: "sm" | "md";
}

function ToggleButton({
  label,
  active,
  onClick,
  size = "sm",
}: ToggleButtonProps) {
  const sizeClasses =
    size === "sm" ? "px-2 py-1 text-[10px]" : "px-3 py-1.5 text-xs";

  return (
    <button
      type="button"
      onClick={onClick}
      className={`${sizeClasses} font-medium rounded-md border transition-colors ${
        active
          ? "bg-blue-600 text-white border-blue-600"
          : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
      }`}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// PrintPreviewTable
// ---------------------------------------------------------------------------

interface PrintPreviewTableProps {
  title: string;
  tasks: SectionBoardTask[];
  profile: GroupingProfile;
  settings: PrintSettings;
}

function PrintPreviewTable({
  title,
  tasks,
  profile,
  settings,
}: PrintPreviewTableProps) {
  const allGroups = useMemo(
    () => groupTasksByProfile(tasks, profile),
    [tasks, profile],
  );

  const groups = useMemo(() => {
    return allGroups
      .filter((g) => g.totalQtyPlan - g.totalQtyDone > 0)
      .filter((g) => {
        if (settings.minQty !== null && g.totalQtyPlan < settings.minQty)
          return false;
        if (settings.maxQty !== null && g.totalQtyPlan > settings.maxQty)
          return false;
        return true;
      });
  }, [allGroups, settings.minQty, settings.maxQty]);

  if (groups.length === 0) return null;

  const hasCol = (col: PrintColumn) => settings.columns.includes(col);
  const showHanger = settings.showQtyPerHanger;

  const getOpNames = (task: SectionBoardTask) => {
    const ops: RouteHistoryOp[] = profile.criteria.includes("routeHistoryAfter")
      ? (task.route_history_after ?? [])
      : (task.route_history ?? []).filter((op) => op.is_significant);
    const unique = new Set<string>();
    for (const op of ops) {
      if (op.is_significant) unique.add(op.operation_name ?? "—");
    }
    return unique.size > 0 ? Array.from(unique).join(" / ") : "—";
  };

  return (
    <div className="mb-4">
      <h3 className="text-xs font-semibold mb-1">{title}</h3>
      <div className="print-lines text-[14px] space-y-0.5">
        {groups.map((group) => {
          const task = group.tasks[0];
          const issued = group.tasks.reduce(
            (s, t) => s + parseFloat(t.cache.issued_quantity),
            0,
          );
          const transferred = group.tasks.reduce(
            (s, t) => s + parseFloat(t.cache.transferred_quantity),
            0,
          );
          const remaining = group.totalQtyPlan - issued;
          const balance = group.totalQtyPlan - group.totalQtyDone;
          const qtyPerHanger = getQtyPerHanger(task);
          const pairedLabel = getPairedHangerLabel(task);
          const { hangers } = adjustQtyToHanger(
            group.totalQtyPlan,
            qtyPerHanger,
          );

          const parts: string[] = [];
          if (hasCol("productSku")) parts.push(task.product_sku);
          if (
            hasCol("operationName") &&
            profile.criteria.includes("operationCode")
          )
            parts.push(getOpNames(task));

          const qtyParts: string[] = [];
          if (hasCol("qtyPlan"))
            qtyParts.push(`План: ${group.totalQtyPlan.toFixed(0)}`);
          if (showHanger) {
            const hangerQty =
              pairedLabel ??
              (qtyPerHanger != null ? String(qtyPerHanger) : "—");
            qtyParts.push(`Подвесов: ${hangers}П (${hangerQty}шт/п)`);
          }
          if (hasCol("qtyRemaining"))
            qtyParts.push(
              `Ост. выдать: ${(remaining >= 0 ? remaining : 0).toFixed(0)}`,
            );
          if (hasCol("qtyTransferred"))
            qtyParts.push(`Передано: ${transferred.toFixed(0)}`);
          if (hasCol("qtyBalance"))
            qtyParts.push(`Остаток: ${balance.toFixed(0)}`);

          if (qtyParts.length > 0) parts.push(qtyParts.join(" | "));

          return (
            <div key={group.key} className="border-b border-gray-200 pb-0.5">
              {parts.join(" | ")}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PlanPrintPreviewModal (Radix Dialog)
// ---------------------------------------------------------------------------

interface PlanPrintPreviewModalProps {
  sectionId: number;
  sectionName: string;
  onClose: () => void;
  hasBefore: boolean;
  hasAfter: boolean;
  tasks: SectionBoardTask[];
  beforeProfile: GroupingProfile;
  afterProfile: GroupingProfile;
  singleProfile: GroupingProfile | null;
  showSingleTable: boolean;
}

export function PlanPrintPreviewModal({
  sectionId,
  sectionName,
  onClose,
  hasBefore,
  hasAfter,
  tasks,
  beforeProfile,
  afterProfile,
  singleProfile,
  showSingleTable,
}: PlanPrintPreviewModalProps) {
  const [settings, setSettings] = useState<PrintSettings>(() =>
    loadSettings(sectionId),
  );
  const previewRef = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<ReactNode[]>([]);

  const title =
    settings.title ||
    `План: ${sectionName} от ${new Date().toLocaleDateString("ru-RU")}`;

  function toggleColumn(col: PrintColumn) {
    setSettings((prev) => {
      const exists = prev.columns.includes(col);
      const next = exists
        ? prev.columns.filter((c) => c !== col)
        : [...prev.columns, col];
      if (next.length === 0) return prev;
      return { ...prev, columns: next };
    });
  }

  function handlePrint() {
    window.print();
  }

  const showBefore =
    settings.tableMode === "before" || settings.tableMode === "both";
  const showAfter =
    settings.tableMode === "after" || settings.tableMode === "both";

  // Auto-save settings on change
  useEffect(() => {
    saveSettings(sectionId, settings);
  }, [sectionId, settings]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const contentBlocks = useMemo(() => {
    const blocks: { title: string; profile: GroupingProfile }[] = [];
    if (showSingleTable && singleProfile) {
      blocks.push({ title: "План", profile: singleProfile });
    } else {
      if (showBefore) blocks.push({ title: "План выдачи на участок", profile: beforeProfile });
      if (showAfter) blocks.push({ title: "План сдачи с участка", profile: afterProfile });
    }
    return blocks;
  }, [showSingleTable, singleProfile, showBefore, showAfter, beforeProfile, afterProfile]);

  // Split content into A4 pages based on actual measured height
  const [renderedPages, setRenderedPages] = useState<ReactNode[]>([]);
  const [isMeasured, setIsMeasured] = useState(false);

  // If no blocks, show empty state immediately without waiting for effect
  useEffect(() => {
    if (contentBlocks.length === 0) {
      setRenderedPages([
        <div key="empty" className="print-page bg-white relative">
          <div className="text-center mb-4">
            <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              Сформировано: {new Date().toLocaleString("ru-RU")} · 1/1
            </div>
          </div>
          <p className="text-center text-muted-foreground py-8 text-sm">Нет данных для печати</p>
        </div>,
      ]);
      setIsMeasured(true);
    }
  }, [contentBlocks.length, title]);

  useEffect(() => {
    if (!previewRef.current) return;
    if (contentBlocks.length === 0) return; // handled by separate useEffect

    const A4_CONTENT_PX = 990; // ~277mm at 96dpi, minus header/footer

    const measure = () => {
      const contentEl = previewRef.current?.querySelector(".print-content-measure");
      if (!contentEl) return;

      const contentHeight = contentEl.scrollHeight;
      const totalPages = Math.max(1, Math.ceil(contentHeight / A4_CONTENT_PX));

      // Get all table blocks
      const blocks = contentEl.querySelectorAll(".print-table-block");

      // If fits on one page
      if (contentHeight <= A4_CONTENT_PX) {
        setRenderedPages([
          <div key="single" className="print-page bg-white relative">
            <div className="text-center mb-4">
              <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
              <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center justify-center gap-2">
                <span>Сформировано: {new Date().toLocaleString("ru-RU")}</span>
                <span className="text-blue-600 font-medium">· 1/1</span>
              </div>
            </div>
            {contentBlocks.map((block, idx) => (
              <PrintPreviewTable key={idx} title={block.title} tasks={tasks} profile={block.profile} settings={settings} />
            ))}
          </div>,
        ]);
        setIsMeasured(true);
        return;
      }

      // Split into multiple pages
      const pages: ReactNode[] = [];
      let currentPageContent: ReactNode[] = [];
      let currentPageHeight = 0;
      let pageNum = 1;

      blocks.forEach((blockEl) => {
        const blockHeight = blockEl.scrollHeight;
        const blockIdx = Array.from(blocks).indexOf(blockEl);
        const block = contentBlocks[blockIdx];

        if (currentPageHeight + blockHeight > A4_CONTENT_PX && currentPageContent.length > 0) {
          pages.push(
            <div key={pageNum} className="print-page bg-white relative">
              <div className="text-center mb-4">
                <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center justify-center gap-2">
                  <span>Сформировано: {new Date().toLocaleString("ru-RU")}</span>
                  <span className="text-blue-600 font-medium">· {pageNum}/{totalPages}</span>
                </div>
              </div>
              {currentPageContent}
            </div>,
          );
          pageNum++;
          currentPageContent = [
            <PrintPreviewTable key={blockIdx} title={block.title} tasks={tasks} profile={block.profile} settings={settings} />,
          ];
          currentPageHeight = blockHeight;
        } else {
          currentPageContent.push(
            <PrintPreviewTable key={blockIdx} title={block.title} tasks={tasks} profile={block.profile} settings={settings} />,
          );
          currentPageHeight += blockHeight;
        }
      });

      if (currentPageContent.length > 0) {
        pages.push(
          <div key={pageNum} className="print-page bg-white relative">
            <div className="text-center mb-4">
              <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
              <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center justify-center gap-2">
                <span>Сформировано: {new Date().toLocaleString("ru-RU")}</span>
                <span className="text-blue-600 font-medium">· {pageNum}/{totalPages}</span>
              </div>
            </div>
            {currentPageContent}
          </div>,
        );
      }

      setRenderedPages(pages);
      setIsMeasured(true);
    };

    // Wait for render then measure
    requestAnimationFrame(() => {
      requestAnimationFrame(measure);
    });
  }, [settings, tasks, contentBlocks, title]);


  return (
    <RadixDialog.Root open onOpenChange={() => onClose()}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[60] bg-black/50" />
        <RadixDialog.Content className="print-preview-sheet fixed left-[50%] top-[50%] z-[60] w-[1600px] max-h-[90vh] translate-x-[-50%] translate-y-[-50%] bg-white shadow-lg rounded-lg overflow-hidden flex flex-col p-0">
          {/* Print styles — как в hrms */}
          <style>{`
            @page { size: A4 portrait; margin: 0; }
            @media print {
              html, body {
                margin: 0 !important; padding: 0 !important; background: white !important;
                height: auto !important; min-height: auto !important; overflow: visible !important;
              }
              body * { visibility: hidden; }
              .print-preview-sheet, .print-preview-sheet * { visibility: visible; }
              body > *:not(.print-preview-sheet):not([data-radix-focus-guard]) { display: none !important; }
              [data-radix-dialog-overlay], [role="presentation"] { display: none !important; visibility: hidden !important; }
              [data-state="open"] > div, .print-preview-sheet, [role="dialog"] {
                position: static !important; left: auto !important; top: auto !important;
                right: auto !important; bottom: auto !important; transform: none !important;
                max-width: none !important; max-height: none !important; min-height: auto !important;
                width: 100% !important; height: auto !important; overflow: visible !important;
                background: white !important; padding: 0 !important; margin: 0 !important;
                border: none !important; border-radius: 0 !important; box-shadow: none !important;
                outline: none !important;
              }
              .no-print { display: none !important; }
              .print-preview-sheet button, .print-preview-sheet [role="button"] { display: none !important; }
              .print-page { page-break-after: always; position: relative; padding: 10mm 15mm; box-sizing: border-box; }
              .print-page:last-child { page-break-after: auto; }
              @media print {
                .print-page { min-height: 297mm; }
              }
              .print-lines { font-size: 14px; line-height: 1.5; word-break: break-word; overflow-wrap: anywhere; }
              .print-lines > div { border-bottom: 0.5px solid #ccc; padding-bottom: 1px; margin-bottom: 1px; page-break-inside: avoid; }
              .print-header { margin-bottom: 4px; text-align: center; }
              .print-header span { display: inline; font-size: 11px; margin: 0; padding: 0; }
            }
          `}</style>

          {/* Header */}
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
              <RadixDialog.Close
                className="text-muted-foreground hover:text-foreground text-2xl leading-none"
                aria-label="Закрыть"
              >
                ×
              </RadixDialog.Close>
            </div>
          </div>

          {/* Content: settings (left) + preview (right) */}
          <div className="flex flex-1 overflow-hidden">
            {/* Left panel: settings */}
            <div className="w-72 shrink-0 border-r overflow-auto p-4 space-y-4 no-print">
              {/* Заголовок */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium">Заголовок</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) =>
                    setSettings((prev) => ({ ...prev, title: e.target.value }))
                  }
                  className="w-full rounded-md border px-2.5 py-1.5 text-xs"
                />
              </div>

              {/* Таблицы */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium">Таблица</label>
                <div className="flex gap-1.5 flex-wrap">
                  {[
                    {
                      key: "before" as TableMode,
                      label: "План выдачи",
                      disabled: !hasBefore,
                    },
                    {
                      key: "after" as TableMode,
                      label: "План сдачи",
                      disabled: !hasAfter,
                    },
                    {
                      key: "both" as TableMode,
                      label: "Оба плана",
                      disabled: !hasBefore || !hasAfter,
                    },
                  ].map((mode) => (
                    <button
                      key={mode.key}
                      type="button"
                      disabled={mode.disabled}
                      onClick={() =>
                        setSettings((prev) => ({
                          ...prev,
                          tableMode: mode.key,
                        }))
                      }
                      className={`px-2.5 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                        mode.disabled
                          ? "opacity-40 cursor-not-allowed bg-gray-100 text-gray-400 border-gray-200"
                          : settings.tableMode === mode.key
                            ? "bg-blue-600 text-white border-blue-600"
                            : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Колонки */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium">Колонки</label>
                <div className="flex gap-1.5 flex-wrap">
                  {ALL_PRINT_COLUMNS.map((col) => (
                    <ToggleButton
                      key={col}
                      label={PRINT_COLUMN_LABELS[col]}
                      active={settings.columns.includes(col)}
                      onClick={() => toggleColumn(col)}
                    />
                  ))}
                </div>
              </div>

              {/* Подвесы */}
              <div className="space-y-1.5">
                <ToggleButton
                  label="Подвесы"
                  active={settings.showQtyPerHanger}
                  onClick={() =>
                    setSettings((prev) => ({
                      ...prev,
                      showQtyPerHanger: !prev.showQtyPerHanger,
                    }))
                  }
                  size="md"
                />
              </div>

              {/* Фильтр по количеству */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium">
                  Фильтр по количеству
                </label>
                <div className="flex gap-1.5">
                  <input
                    type="number"
                    min={0}
                    value={settings.minQty ?? ""}
                    onChange={(e) =>
                      setSettings((prev) => ({
                        ...prev,
                        minQty:
                          e.target.value === "" ? null : Number(e.target.value),
                      }))
                    }
                    className="w-20 rounded-md border px-2 py-1.5 text-xs"
                    placeholder="от"
                  />
                  <span className="self-center text-xs text-muted-foreground">
                    —
                  </span>
                  <input
                    type="number"
                    min={0}
                    value={settings.maxQty ?? ""}
                    onChange={(e) =>
                      setSettings((prev) => ({
                        ...prev,
                        maxQty:
                          e.target.value === "" ? null : Number(e.target.value),
                      }))
                    }
                    className="w-20 rounded-md border px-2 py-1.5 text-xs"
                    placeholder="до"
                  />
                </div>
              </div>
            </div>

            {/* Right panel: live preview */}
            <div className="flex-1 overflow-auto bg-white">
              <div
                ref={previewRef}
                className="mx-auto"
                style={{ width: "210mm", padding: "10mm 15mm" }}
              >
                {/* Hidden measurement container */}
                <div className="absolute opacity-0 pointer-events-none overflow-hidden" style={{ width: "210mm", padding: "10mm 15mm" }}>
                  <div className="print-content-measure">
                    {contentBlocks.map((block) => (
                      <div key={block.title} className="print-table-block">
                        <PrintPreviewTable title={block.title} tasks={tasks} profile={block.profile} settings={settings} />
                      </div>
                    ))}
                  </div>
                </div>

                {/* Show content directly while measuring */}
                {!isMeasured && contentBlocks.length > 0 && (
                  <div className="print-page bg-white relative">
                    <div className="text-center mb-4">
                      <div className="text-sm font-bold uppercase tracking-wide">{title}</div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        Сформировано: {new Date().toLocaleString("ru-RU")}
                      </div>
                    </div>
                    {contentBlocks.map((block, idx) => (
                      <PrintPreviewTable key={idx} title={block.title} tasks={tasks} profile={block.profile} settings={settings} />
                    ))}
                  </div>
                )}

                {/* Rendered pages after measurement */}
                {isMeasured && renderedPages}
              </div>
            </div>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

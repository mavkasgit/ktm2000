/**
 * Модальное окно плана участка.
 *
 * Для анодирования показывается единое дерево: предоперации, анодирование и
 * упаковка остаются в строке одного задания. Верхняя группировка переключается
 * между артикулом и цветом анодирования.
 */

import { useEffect, useMemo, useState } from "react";
import type { SectionBoardTask, SectionOperation } from "@/shared/api/shopfloor";
import { PlanTaskTable } from "./PlanTaskTable";
import type { PlanTaskGroupingMode } from "../lib/planTaskGroups";
import {
  addPreset,
  deletePreset,
  findMatchingPresetId,
  isSameSettings,
  loadPresets,
  type PlanPreset,
} from "../lib/planPresets";
import {
  PlanPrintPreviewModal,
  ALL_PRINT_COLUMNS,
  PRINT_COLUMN_LABELS,
  type PrintColumn,
  type PrintSettings,
} from "./PlanPrintPreviewModal";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/shared/ui";

interface PlanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sectionId: number;
  sectionName: string;
  tasks: SectionBoardTask[];
  availableOperations?: SectionOperation[];
}

const DEFAULT_PRINT_SETTINGS: PrintSettings = {
  tableMode: "both",
  columns: ALL_PRINT_COLUMNS,
  title: "",
  showQtyPerHanger: true,
  minQty: null,
  maxQty: null,
};

function loadPrintSettings(sectionId: number): PrintSettings {
  try {
    const raw = localStorage.getItem(`plan-print-settings-${sectionId}`);
    if (!raw) return { ...DEFAULT_PRINT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<PrintSettings>;
    return {
      ...DEFAULT_PRINT_SETTINGS,
      ...parsed,
      columns: Array.isArray(parsed.columns) ? parsed.columns : ALL_PRINT_COLUMNS,
    };
  } catch {
    return { ...DEFAULT_PRINT_SETTINGS };
  }
}

function savePrintSettings(sectionId: number, settings: PrintSettings) {
  localStorage.setItem(`plan-print-settings-${sectionId}`, JSON.stringify(settings));
}

function loadGroupingMode(sectionId: number): PlanTaskGroupingMode {
  return localStorage.getItem(`plan-grouping-mode-${sectionId}`) === "anodizingColor"
    ? "anodizingColor"
    : "article";
}

export function PlanModal({
  open,
  onOpenChange,
  sectionId,
  sectionName,
  tasks,
}: PlanModalProps) {
  const [groupingMode, setGroupingMode] = useState<PlanTaskGroupingMode>(() => loadGroupingMode(sectionId));
  const [printSettings, setPrintSettings] = useState<PrintSettings>(() => loadPrintSettings(sectionId));
  const [printSettingsOpen, setPrintSettingsOpen] = useState(false);
  const [hiddenGroupKeys, setHiddenGroupKeys] = useState<Set<string>>(() => new Set());
  const [presets, setPresets] = useState<PlanPreset[]>(() => loadPresets(sectionId));
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [newPresetName, setNewPresetName] = useState("");
  const [presetToDelete, setPresetToDelete] = useState<PlanPreset | null>(null);

  useEffect(() => {
    setGroupingMode(loadGroupingMode(sectionId));
    setPrintSettings(loadPrintSettings(sectionId));
    setPresets(loadPresets(sectionId));
    setActivePresetId(null);
    setHiddenGroupKeys(new Set());
  }, [sectionId]);

  useEffect(() => {
    localStorage.setItem(`plan-grouping-mode-${sectionId}`, groupingMode);
  }, [groupingMode, sectionId]);

  useEffect(() => {
    savePrintSettings(sectionId, printSettings);
  }, [sectionId, printSettings]);

  useEffect(() => {
    const activePreset = presets.find((preset) => preset.id === activePresetId);
    if (activePresetId && !activePreset) {
      setActivePresetId(null);
    } else if (activePreset && !isSameSettings(activePreset.settings, printSettings)) {
      setActivePresetId(null);
    } else if (activePresetId === null) {
      const match = findMatchingPresetId(presets, printSettings);
      if (match) setActivePresetId(match);
    }
  }, [printSettings, presets, activePresetId]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !printSettingsOpen) onOpenChange(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, printSettingsOpen, onOpenChange]);

  const hideGroup = (key: string) => {
    setHiddenGroupKeys((previous) => new Set(previous).add(key));
  };

  const toggleColumn = (column: PrintColumn) => {
    setPrintSettings((previous) => ({
      ...previous,
      columns: previous.columns.includes(column)
        ? previous.columns.filter((item) => item !== column)
        : [...previous.columns, column],
    }));
  };

  const applyPreset = (preset: PlanPreset) => {
    setPrintSettings(preset.settings);
    setActivePresetId(preset.id);
  };

  const handleSavePreset = () => {
    const name = newPresetName.trim();
    if (!name) return;
    const created = addPreset(sectionId, name, printSettings);
    setPresets(loadPresets(sectionId));
    setActivePresetId(created.id);
    setNewPresetName("");
  };

  const confirmDeletePreset = () => {
    if (!presetToDelete) return;
    deletePreset(sectionId, presetToDelete.id);
    setPresets(loadPresets(sectionId));
    if (activePresetId === presetToDelete.id) setActivePresetId(null);
    setPresetToDelete(null);
  };

  const filteredTasks = useMemo(() => {
    if (printSettings.minQty == null && printSettings.maxQty == null) return tasks;
    return tasks.filter((task) => {
      const quantity = Number(task.planned_quantity) || 0;
      if (printSettings.minQty != null && quantity < printSettings.minQty) return false;
      if (printSettings.maxQty != null && quantity > printSettings.maxQty) return false;
      return true;
    });
  }, [tasks, printSettings.minQty, printSettings.maxQty]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
      onClick={(event) => event.target === event.currentTarget && onOpenChange(false)}
    >
      <style>{`
        @page { size: A4 landscape; margin: 10mm; }
        @media print {
          html, body { margin: 0 !important; padding: 0 !important; background: white !important; height: auto !important; overflow: visible !important; }
          body * { visibility: hidden; }
          .print-area, .print-area * { visibility: visible; }
          body > *:not(.print-area):not([data-radix-focus-guard]) { display: none !important; }
          .print-area { position: static !important; max-width: none !important; max-height: none !important; overflow: visible !important; }
          .no-print { display: none !important; }
        }
      `}</style>
      <div className="bg-white rounded-lg shadow-xl w-[92vw] max-w-[1500px] max-h-[92vh] flex flex-col m-4 print-area" role="dialog" aria-modal="true" aria-label={`План: ${sectionName}`}>
        <div className="p-4 border-b space-y-3 no-print">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">План: {sectionName}</h2>
            <div className="flex items-center gap-2">
              <kbd className="hidden sm:inline-block text-[10px] text-muted-foreground border rounded px-1.5 py-0.5 font-mono">ESC</kbd>
              <button type="button" className="text-muted-foreground hover:text-foreground text-2xl leading-none" onClick={() => onOpenChange(false)} aria-label="Закрыть">×</button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium text-muted-foreground">Пресеты:</span>
            {presets.map((preset) => (
              <div key={preset.id} className="relative group">
                <button
                  type="button"
                  onClick={() => applyPreset(preset)}
                  className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${activePresetId === preset.id ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"}`}
                >
                  {preset.isBuiltin ? `★ ${preset.name}` : preset.name}
                </button>
                {!preset.isBuiltin && (
                  <button type="button" onClick={() => setPresetToDelete(preset)} className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center h-4 w-4 rounded-full bg-red-500 text-white text-[10px]" title="Удалить пресет">×</button>
                )}
              </div>
            ))}
            <div className="flex items-center gap-1 ml-1">
              <input value={newPresetName} onChange={(event) => setNewPresetName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && handleSavePreset()} placeholder="Название пресета" className="w-36 rounded-md border px-2 py-1 text-xs" />
              <button type="button" onClick={handleSavePreset} disabled={!newPresetName.trim()} className="px-2 py-1 text-xs border rounded-md disabled:opacity-40" title="Сохранить пресет">Сохранить</button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Группировка:</span>
              <div className="flex gap-1">
                {([
                  { key: "article" as const, label: "По артикулу" },
                  { key: "anodizingColor" as const, label: "По цвету анодирования" },
                ]).map((option) => (
                  <button key={option.key} type="button" onClick={() => setGroupingMode(option.key)} className={`px-2 py-1 rounded-md border text-[11px] font-medium ${groupingMode === option.key ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"}`}>
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Кол-во:</span>
              <input type="number" min={0} value={printSettings.minQty ?? ""} onChange={(event) => setPrintSettings((previous) => ({ ...previous, minQty: event.target.value === "" ? null : Number(event.target.value) }))} className="w-16 rounded-md border px-2 py-1 text-xs" placeholder="от" />
              <span>—</span>
              <input type="number" min={0} value={printSettings.maxQty ?? ""} onChange={(event) => setPrintSettings((previous) => ({ ...previous, maxQty: event.target.value === "" ? null : Number(event.target.value) }))} className="w-16 rounded-md border px-2 py-1 text-xs" placeholder="до" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Колонки печати:</span>
              {ALL_PRINT_COLUMNS.map((column) => (
                <button key={column} type="button" onClick={() => toggleColumn(column)} className={`px-2 py-1 text-[11px] rounded-md border ${printSettings.columns.includes(column) ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300"}`}>
                  {PRINT_COLUMN_LABELS[column]}
                </button>
              ))}
            </div>
            <button type="button" onClick={() => setPrintSettingsOpen(true)} className="ml-auto px-3 py-1.5 rounded-md bg-blue-600 text-white text-xs font-medium hover:bg-blue-700">Печать</button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {hiddenGroupKeys.size > 0 && (
            <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Скрыто групп: <b>{hiddenGroupKeys.size}</b>
              <button type="button" onClick={() => setHiddenGroupKeys(new Set())} className="ml-auto px-2 py-1 rounded-md border border-amber-300 bg-white">Показать все</button>
            </div>
          )}
          <PlanTaskTable tasks={filteredTasks} mode={groupingMode} hiddenGroupKeys={hiddenGroupKeys} onHideGroup={hideGroup} />
        </div>

        <div className="flex justify-end p-4 border-t no-print">
          <button type="button" className="px-4 py-2 rounded-md border hover:bg-gray-50 text-sm" onClick={() => onOpenChange(false)}>Закрыть</button>
        </div>
      </div>

      {printSettingsOpen && (
        <PlanPrintPreviewModal
          sectionName={sectionName}
          onClose={() => setPrintSettingsOpen(false)}
          tasks={filteredTasks}
          settings={printSettings}
          groupingMode={groupingMode}
          hiddenGroupKeys={hiddenGroupKeys}
        />
      )}

      <AlertDialog open={!!presetToDelete} onOpenChange={(open) => !open && setPresetToDelete(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader><AlertDialogTitle>Удалить пресет?</AlertDialogTitle><AlertDialogDescription>Пресет «{presetToDelete?.name}» будет удалён.</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>Отмена</AlertDialogCancel><AlertDialogAction onClick={confirmDeletePreset} className="bg-destructive text-destructive-foreground">Удалить</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

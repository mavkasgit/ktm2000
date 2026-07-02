/**
 * components/PlanModal.tsx
 * =========================
 * Модальное окно просмотра плана для участка.
 *
 * Две таблицы:
 *   - План выдачи: что приходит на участок (ещё не полностью принято)
 *   - План сдачи: что уходит с участка (завершено, но не полностью передано)
 *
 * Каждая таблица имеет свой независимый профиль группировки (localStorage).
 */

import React, { useEffect, useMemo, useState } from "react";
import type { SectionBoardTask, RouteHistoryOp, SectionOperation } from "@/shared/api/shopfloor";
import { groupTasksByProfile } from "../lib/groupTasksByProfile";
import { GroupingSettingsModal } from "./GroupingSettingsModal";
import { PRESET_PROFILES, type GroupingProfile } from "../lib/groupingProfiles";
import { PlanPrintPreviewModal, ALL_PRINT_COLUMNS, PRINT_COLUMN_LABELS, type PrintColumn, type PrintSettings, type TableMode } from "./PlanPrintPreviewModal";
import {
  addPreset,
  deletePreset,
  findMatchingPresetId,
  isSameSettings,
  loadPresets,
  type PlanPreset,
} from "../lib/planPresets";
import { renderIcon, AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/shared/ui";


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

interface PlanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sectionId: number;
  sectionName: string;
  tasks: SectionBoardTask[];
  availableOperations?: SectionOperation[];
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadProfile(key: string, defaultProfileId = "sku+routeHistory"): GroupingProfile {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed = JSON.parse(raw) as GroupingProfile;
      if (parsed.id && Array.isArray(parsed.criteria)) {
        // Validate profile has required criteria for its type
        if ((parsed.id === "sku+routeHistory" || parsed.id === "sku+routeHistoryAfter") && !parsed.criteria.includes("operationCode")) {
          // Stale profile — return updated default
          return PRESET_PROFILES.find(p => p.id === defaultProfileId)!;
        }
        return parsed;
      }
    }
  } catch {}
  return PRESET_PROFILES.find(p => p.id === defaultProfileId)!;
}

function saveProfile(key: string, profile: GroupingProfile) {
  try {
    localStorage.setItem(key, JSON.stringify(profile));
  } catch {}
}

function sumCache(
  groups: ReturnType<typeof groupTasksByProfile>,
  accessor: (t: SectionBoardTask) => number,
): number {
  return groups.reduce(
    (s, g) => s + g.tasks.reduce((ss, t) => ss + accessor(t), 0),
    0,
  );
}

/** Insert zero-width spaces after '+' so line breaks happen after the plus, not mid-SKU. Also strip trailing arrow. */
function renderSkuWithBreakHints(sku: string): React.ReactNode {
  const cleaned = sku.replace(/\s*→\s*$/, '');
  const parts = cleaned.split(/(\+)/g);
  if (parts.length <= 1) return cleaned;
  return parts.map((part, i) =>
    part === "+" ? <span key={i}>+<wbr /></span> : <React.Fragment key={i}>{part}</React.Fragment>
  );
}


// ---------------------------------------------------------------------------
// PlanTable — переиспользуемая таблица (issue / send)
// ---------------------------------------------------------------------------

interface PlanTableProps {
  title: string;
  tasks: SectionBoardTask[];
  profile: GroupingProfile;
  onSettingsClick: () => void;
  emptyMessage?: string;
  printSettings?: PrintSettings;
  onHideGroup?: (groupKey: string) => void;
  isHidden?: (groupKey: string) => boolean;
}

function PlanTable({
  title,
  tasks,
  profile,
  onSettingsClick,
  emptyMessage,
  printSettings,
  onHideGroup,
  isHidden,
}: PlanTableProps) {
  const allGroups = useMemo(() => groupTasksByProfile(tasks, profile), [tasks, profile]);

  const groups = useMemo(() => {
    return allGroups
      .filter((g) => g.totalQtyPlan - g.totalQtyDone > 0)
      .filter((g) => {
        if (!printSettings) return true;
        if (printSettings.minQty !== null && g.totalQtyPlan < printSettings.minQty) return false;
        if (printSettings.maxQty !== null && g.totalQtyPlan > printSettings.maxQty) return false;
        return true;
      })
      .filter((g) => !isHidden?.(g.key));
  }, [allGroups, printSettings, isHidden]);

  const showSku = !printSettings || printSettings.columns.includes("productSku");
  const showOp = !printSettings || printSettings.columns.includes("operationName");
  const showQtyPlan = !printSettings || printSettings.columns.includes("qtyPlan");
  const showQtyRemaining = !printSettings || printSettings.columns.includes("qtyRemaining");
  const showQtyTransferred = !printSettings || printSettings.columns.includes("qtyTransferred");
  const showQtyBalance = !printSettings || printSettings.columns.includes("qtyBalance");

  const totalQtyPlan = useMemo(
    () => groups.reduce((sum, g) => sum + g.totalQtyPlan, 0),
    [groups],
  );

  const totalIssued = useMemo(() => sumCache(groups, (t) => parseFloat(t.cache.issued_quantity)), [groups]);
  const totalTransferred = useMemo(() => sumCache(groups, (t) => parseFloat(t.cache.transferred_quantity)), [groups]);
  const totalDone = useMemo(() => groups.reduce((s, g) => s + g.totalQtyDone, 0), [groups]);
  const totalOrders = useMemo(() => groups.reduce((s, g) => s + g.tasks.length, 0), [groups]);

  const colSpan = 1 +
    (profile.criteria.includes("operationCode") ? 2 : 0) +
    (profile.criteria.includes("outputKind") ? 1 : 0) +
    (profile.criteria.includes("sourceRef") ? 1 : 0);

  if (tasks.length === 0) {
    return (
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button
            className="text-xs font-medium text-blue-600 hover:text-blue-800 underline"
            onClick={onSettingsClick}
          >
            {profile.name}
          </button>
        </div>
        <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">
          {emptyMessage ?? "Нет данных"}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <button
          className="text-xs font-medium text-blue-600 hover:text-blue-800 underline"
          onClick={onSettingsClick}
        >
          {profile.name}
        </button>
      </div>

      <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse table-auto">
        <thead>
          <tr className="border-b">
            {showSku && (
              <th className="text-left px-2 py-2 font-medium max-w-[120px] break-words">Артикул</th>
            )}
            {showOp && profile.criteria.includes("operationCode") && (
              <>
                <th className="text-left px-2 py-2 font-medium w-[1px] whitespace-nowrap">Маршрут</th>
                <th className="text-left px-2 py-2 font-medium max-w-[140px] break-words">Операция</th>
              </>
            )}
            {profile.criteria.includes("outputKind") && (
              <th className="text-left px-2 py-2 font-medium">Цвет</th>
            )}
            {profile.criteria.includes("sourceRef") && (
              <th className="text-left px-2 py-2 font-medium">Заказ</th>
            )}
            {showQtyPlan && (
              <th className="text-right px-2 py-2 font-medium whitespace-nowrap">План</th>
            )}
            {showQtyRemaining && (
              <th className="text-right px-2 py-2 font-medium whitespace-nowrap" style={{ minWidth: "60px" }}>Осталось<br/>выдать</th>
            )}
            {showQtyTransferred && (
              <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Передано</th>
            )}
            {showQtyBalance && (
              <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Остаток</th>
            )}
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Заказов</th>
            {onHideGroup && <th className="w-8"></th>}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const task = group.tasks[0];

            // Build the full sequence of significant operations for display.
            // For routeHistory profile ("До"): ONLY route_history (previous sections, NOT including current)
            // For routeHistoryAfter profile ("После"): route_history_after (includes current section's operation)
            // Only include significant operations (is_significant=true).
            const isAfterProfile = profile.criteria.includes("routeHistoryAfter");
            const allOps: RouteHistoryOp[] = isAfterProfile
              ? (task.route_history_after ?? [])
              : (task.route_history ?? []).filter((op) => op.is_significant);

            // Chips display — all significant ops including current
            const chipOps: RouteHistoryOp[] = allOps;

            // Collect unique operation names for the main display line
            const uniqueOpNames = new Set<string>();
            for (const op of allOps) {
              if (op.is_significant) {
                uniqueOpNames.add(op.operation_name ?? "—");
              }
            }

            return (
              <tr key={group.key} className="border-b hover:bg-gray-50">
                {/* Артикул */}
                {showSku && (
                  <td className="px-2 py-2 max-w-[120px] break-words">
                    {renderSkuWithBreakHints(task.product_sku)}
                  </td>
                )}

                {/* Операция — split into Маршрут (chips) + Операция (text) */}
                {showOp && profile.criteria.includes("operationCode") && (
                  <>
                    {/* Маршрут — icon chips */}
                    <td className="px-2 py-2">
                      {chipOps.length > 0 ? (
                        <div className="flex items-center gap-1">
                          {chipOps.map((op: RouteHistoryOp, i: number) => (
                            <React.Fragment key={i}>
                              {i > 0 && <span className="text-muted-foreground">→</span>}
                              <span
                                className="inline-flex items-center justify-center w-5 h-5 rounded bg-gray-100 text-[9px] font-medium"
                                style={{ color: op.icon_color || undefined }}
                                title={op.operation_name}
                              >
                                {op.icon ? renderIcon(op.icon, "h-3 w-3") : (op.operation_name || "?")[0]}
                              </span>
                            </React.Fragment>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    {/* Операция — text */}
                    <td className="px-2 py-2 text-sm max-w-[140px] break-words">
                      <div className="font-medium">
                        {uniqueOpNames.size > 0 ? Array.from(uniqueOpNames).join(" / ") : "—"}
                      </div>
                    </td>
                  </>
                )}

                {/* Цвет */}
                {profile.criteria.includes("outputKind") && (
                  <td className="px-2 py-2 text-sm">{task.output_kind ?? "—"}</td>
                )}

                {/* Заказ */}
                {profile.criteria.includes("sourceRef") && (
                  <td className="px-2 py-2 text-sm">{task.source_ref ?? "—"}</td>
                )}

                {/* Количество */}
                {showQtyPlan && (
                  <td className="px-2 py-2 text-right font-medium">
                    {group.totalQtyPlan.toFixed(0)}
                  </td>
                )}
                {showQtyRemaining && (
                  <td className="px-2 py-2 text-right">
                    {(group.totalQtyPlan - totalIssued >= 0 ? group.totalQtyPlan - sumCache([group], (t) => parseFloat(t.cache.issued_quantity)) : 0).toFixed(0)}
                  </td>
                )}
                {showQtyTransferred && (
                  <td className="px-2 py-2 text-right">
                    {sumCache([group], (t) => parseFloat(t.cache.transferred_quantity)).toFixed(0)}
                  </td>
                )}
                {showQtyBalance && (
                  <td className="px-2 py-2 text-right text-blue-700 font-semibold">
                    {(group.totalQtyPlan - group.totalQtyDone).toFixed(0)}
                  </td>
                )}

                {/* Кол-во заказов */}
                <td className="px-2 py-2 text-right text-muted-foreground">
                  {group.tasks.length}
                </td>

                {/* Кнопка скрытия */}
                {onHideGroup && (
                  <td className="px-1 py-2 text-center">
                    <button
                      type="button"
                      onClick={() => onHideGroup(group.key)}
                      className="text-muted-foreground hover:text-red-600 text-base leading-none w-6 h-6 inline-flex items-center justify-center rounded hover:bg-red-50"
                      title="Скрыть из плана"
                    >
                      ×
                    </button>
                  </td>
                )}
              </tr>
            );
          })}

          {/* Итого */}
          <tr className="border-t font-semibold bg-gray-50">
            <td colSpan={colSpan} className="px-2 py-2">Итого</td>
            {showQtyPlan && (
              <td className="px-2 py-2 text-right">{totalQtyPlan.toFixed(0)}</td>
            )}
            {showQtyRemaining && (
              <td className="px-2 py-2 text-right">{(totalQtyPlan - totalIssued >= 0 ? totalQtyPlan - totalIssued : 0).toFixed(0)}</td>
            )}
            {showQtyTransferred && (
              <td className="px-2 py-2 text-right">{totalTransferred.toFixed(0)}</td>
            )}
            {showQtyBalance && (
              <td className="px-2 py-2 text-right text-blue-700">{(totalQtyPlan - totalDone).toFixed(0)}</td>
            )}
            <td className="px-2 py-2 text-right text-muted-foreground">{totalOrders}</td>
            {onHideGroup && <td></td>}
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// PrintSettings — утилиты localStorage (раньше жили в PlanPrintPreviewModal)
// ---------------------------------------------------------------------------

const DEFAULT_PRINT_SETTINGS: PrintSettings = {
  tableMode: "both",
  columns: ALL_PRINT_COLUMNS,
  title: "",
  showQtyPerHanger: false,
  minQty: null,
  maxQty: null,
};

function loadPrintSettings(sectionId: number): PrintSettings {
  try {
    const raw = localStorage.getItem(`plan-print-settings-${sectionId}`);
    if (raw) {
      const parsed = JSON.parse(raw) as PrintSettings;
      if (parsed.tableMode && Array.isArray(parsed.columns)) {
        return parsed;
      }
    }
  } catch {}
  return { ...DEFAULT_PRINT_SETTINGS };
}

function savePrintSettings(sectionId: number, settings: PrintSettings) {
  try {
    localStorage.setItem(
      `plan-print-settings-${sectionId}`,
      JSON.stringify(settings),
    );
  } catch {}
}

// ---------------------------------------------------------------------------
// PlanModal
// ---------------------------------------------------------------------------

export function PlanModal({
  open,
  onOpenChange,
  sectionId,
  sectionName,
  tasks,
  availableOperations,
}: PlanModalProps) {
  const [beforeSettingsOpen, setBeforeSettingsOpen] = useState(false);
  const [afterSettingsOpen, setAfterSettingsOpen] = useState(false);
  const [printSettingsOpen, setPrintSettingsOpen] = useState(false);

  const [printSettings, setPrintSettings] = useState<PrintSettings>(() =>
    loadPrintSettings(sectionId),
  );

  // Пресеты настроек печати
  const [presets, setPresets] = useState<PlanPreset[]>(() => loadPresets(sectionId));
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  // Временно скрытые группы (сбрасывается при закрытии модалки)
  const [hiddenGroupKeys, setHiddenGroupKeys] = useState<Set<string>>(
    () => new Set(),
  );

  function hideGroup(key: string) {
    setHiddenGroupKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }

  function showAllGroups() {
    setHiddenGroupKeys(new Set());
  }

  function isGroupHidden(key: string): boolean {
    return hiddenGroupKeys.has(key);
  }
  const [newPresetName, setNewPresetName] = useState("");
  const [presetToDelete, setPresetToDelete] = useState<PlanPreset | null>(null);

  const [beforeProfile, setBeforeProfile] = useState<GroupingProfile>(() =>
    loadProfile(`plan-before-group-profile-${sectionId}`, "sku+routeHistory"),
  );
  const [afterProfile, setAfterProfile] = useState<GroupingProfile>(() =>
    loadProfile(`plan-after-group-profile-${sectionId}`, "sku+routeHistoryAfter"),
  );

  // Обновить профили при смене sectionId
  useEffect(() => {
    setBeforeProfile(loadProfile(`plan-before-group-profile-${sectionId}`, "sku+routeHistory"));
    setAfterProfile(loadProfile(`plan-after-group-profile-${sectionId}`, "sku+routeHistoryAfter"));
    setPrintSettings(loadPrintSettings(sectionId));
    setPresets(loadPresets(sectionId));
    setActivePresetId(null);
    setHiddenGroupKeys(new Set());
  }, [sectionId]);

  // Если текущие настройки перестали совпадать с активным пресетом — сбрасываем выбор
  useEffect(() => {
    const activePreset = presets.find((p) => p.id === activePresetId);
    if (activePresetId && !activePreset) {
      setActivePresetId(null);
      return;
    }
    if (activePreset && !isSameSettings(activePreset.settings, printSettings)) {
      setActivePresetId(null);
      return;
    }
    if (activePresetId === null) {
      const match = findMatchingPresetId(presets, printSettings);
      if (match) setActivePresetId(match);
    }
  }, [printSettings, presets, activePresetId]);

  function applyPreset(preset: PlanPreset) {
    setPrintSettings({ ...preset.settings });
    setActivePresetId(preset.id);
  }

  function handleSavePreset() {
    const name = newPresetName.trim();
    if (!name) return;
    const created = addPreset(sectionId, name, printSettings);
    setPresets(loadPresets(sectionId));
    setActivePresetId(created.id);
    setNewPresetName("");
  }

  function requestDeletePreset(preset: PlanPreset) {
    if (preset.isBuiltin) return;
    setPresetToDelete(preset);
  }

  function confirmDeletePreset() {
    if (!presetToDelete) return;
    deletePreset(sectionId, presetToDelete.id);
    setPresets(loadPresets(sectionId));
    if (activePresetId === presetToDelete.id) setActivePresetId(null);
    setPresetToDelete(null);
  }

  // Auto-save print settings on change
  useEffect(() => {
    savePrintSettings(sectionId, printSettings);
  }, [sectionId, printSettings]);

  // ESC закрывает окно плана (НЕ превью печати — там свой Radix Dialog).
  // Не срабатывает, когда открыто модальное окно печати.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (printSettingsOpen) return; // отдаём ESC окну печати
      onOpenChange(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, printSettingsOpen, onOpenChange]);

  function toggleColumn(col: PrintColumn) {
    setPrintSettings((prev) => {
      const exists = prev.columns.includes(col);
      const next = exists
        ? prev.columns.filter((c) => c !== col)
        : [...prev.columns, col];
      if (next.length === 0) return prev;
      return { ...prev, columns: next };
    });
  }

  // Задачи уже отфильтрованы по section_id на бэкенде (get_section_board).
  // "До" и "После" — одни и те же задачи, но с разной группировкой:
  //   До = по route_history (что приходит на участок)
  //   После = по route_history_after (что уйдёт с участка после завершения)
  const filteredTasks = tasks;

  // Check if "До" and "После" are effectively identical:
  // no significant operations and no route history at all.
  // In that case, show a single table without the operation column.
  const hasSignificantOps = useMemo(
    () => filteredTasks.some((t) => t.is_significant),
    [filteredTasks],
  );
  const hasRouteHistory = useMemo(
    () => filteredTasks.some((t) => (t.route_history ?? []).length > 0),
    [filteredTasks],
  );
  const showSingleTable = !hasSignificantOps && !hasRouteHistory;

  // When showing single table, use a profile without operationCode
  const singleProfile = useMemo(() => {
    if (showSingleTable) {
      return { ...beforeProfile, criteria: beforeProfile.criteria.filter((c) => c !== "operationCode" && c !== "routeHistory" && c !== "routeHistoryAfter") };
    }
    return null;
  }, [showSingleTable, beforeProfile]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
      onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
    >
      <style>{`
        @page { size: A4 portrait; margin: 10mm; }
        @media print {
          html, body {
            margin: 0 !important; padding: 0 !important; background: white !important;
            height: auto !important; min-height: auto !important; overflow: visible !important;
          }
          body * { visibility: hidden; }
          .print-area, .print-area * { visibility: visible; }
          body > *:not(.print-area):not([data-radix-focus-guard]) { display: none !important; }
          [data-radix-dialog-overlay], [role="presentation"] { display: none !important; visibility: hidden !important; }
          .print-area {
            position: static !important; left: auto !important; top: auto !important;
            right: auto !important; bottom: auto !important; transform: none !important;
            max-width: none !important; max-height: none !important; min-height: auto !important;
            width: 100% !important; height: auto !important; overflow: visible !important;
            background: white !important; padding: 0 !important; margin: 0 !important;
            border: none !important; border-radius: 0 !important; box-shadow: none !important;
            outline: none !important;
          }
          .no-print { display: none !important; }
        }
      `}</style>
      <div className="bg-white rounded-lg shadow-xl w-[80vw] max-w-7xl max-h-[90vh] flex flex-col m-4 print-area" role="dialog" aria-modal>

        {/* Заголовок + полоса фильтров печати */}
        <div className="p-4 border-b space-y-2 no-print">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">План: {sectionName}</h2>
            <div className="flex items-center gap-1">
              <kbd className="hidden sm:inline-block text-[10px] text-muted-foreground border rounded px-1.5 py-0.5 font-mono">ESC</kbd>
              <button
                className="text-muted-foreground hover:text-foreground text-2xl leading-none"
                onClick={() => onOpenChange(false)}
                aria-label="Закрыть"
              >
                ×
              </button>
            </div>
          </div>

          {/* Пресеты настроек */}
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium text-muted-foreground">Пресеты:</span>
            {presets.map((p) => {
              const isActive = activePresetId === p.id
              return (
                <div key={p.id} className="relative group">
                  <button
                    type="button"
                    onClick={() => applyPreset(p)}
                    className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                      isActive
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                    }`}
                    title={`Применить пресет «${p.name}»`}
                  >
                    {p.isBuiltin ? `★ ${p.name}` : p.name}
                  </button>
                  {!p.isBuiltin && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        requestDeletePreset(p)
                      }}
                      className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center h-4 w-4 rounded-full bg-red-500 text-white text-[10px] leading-none hover:bg-red-600"
                      title={`Удалить пресет «${p.name}»`}
                    >
                      ×
                    </button>
                  )}
                </div>
              )
            })}
            <div className="flex items-center gap-1 ml-1">
              <input
                type="text"
                value={newPresetName}
                onChange={(e) => setNewPresetName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newPresetName.trim()) handleSavePreset()
                }}
                placeholder="Название пресета"
                className="w-36 rounded-md border px-2 py-1 text-xs bg-white"
              />
              <button
                type="button"
                onClick={handleSavePreset}
                disabled={!newPresetName.trim()}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md border bg-white text-gray-700 border-gray-300 hover:bg-gray-50 text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                title="Сохранить текущие настройки как новый пресет"
              >
                💾
              </button>
            </div>
          </div>

          {/* Полоса фильтров: всё, что раньше было в левой панели предпросмотра */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
            {/* Таблицы (До / После / Оба) */}
            {!showSingleTable && (
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-muted-foreground">Таблица:</span>
                <div className="flex gap-1">
                  {[
                    { key: "before" as TableMode, label: "Выдача" },
                    { key: "after" as TableMode, label: "Сдача" },
                    { key: "both" as TableMode, label: "Оба" },
                  ].map((mode) => (
                    <button
                      key={mode.key}
                      type="button"
                      onClick={() =>
                        setPrintSettings((prev) => ({ ...prev, tableMode: mode.key }))
                      }
                      className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                        printSettings.tableMode === mode.key
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Заголовок */}
            <div className="flex items-center gap-1.5">
              <label className="font-medium text-muted-foreground">Заголовок:</label>
              <input
                type="text"
                value={printSettings.title}
                onChange={(e) =>
                  setPrintSettings((prev) => ({ ...prev, title: e.target.value }))
                }
                placeholder={`План: ${sectionName} от ${new Date().toLocaleDateString("ru-RU")}`}
                className="w-56 rounded-md border px-2 py-1 text-xs"
              />
            </div>

            {/* Колонки */}
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Колонки:</span>
              <div className="flex gap-1 flex-wrap">
                {ALL_PRINT_COLUMNS.map((col) => (
                  <button
                    key={col}
                    type="button"
                    onClick={() => toggleColumn(col)}
                    className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                      printSettings.columns.includes(col)
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                    }`}
                    title={PRINT_COLUMN_LABELS[col]}
                  >
                    {PRINT_COLUMN_LABELS[col]}
                  </button>
                ))}
              </div>
            </div>

            {/* Подвесы */}
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Подвесы:</span>
              <button
                type="button"
                onClick={() =>
                  setPrintSettings((prev) => ({
                    ...prev,
                    showQtyPerHanger: !prev.showQtyPerHanger,
                  }))
                }
                className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                  printSettings.showQtyPerHanger
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {printSettings.showQtyPerHanger ? "Да" : "Нет"}
              </button>
            </div>

            {/* Фильтр по количеству */}
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-muted-foreground">Кол-во:</span>
              <input
                type="number"
                min={0}
                value={printSettings.minQty ?? ""}
                onChange={(e) =>
                  setPrintSettings((prev) => ({
                    ...prev,
                    minQty:
                      e.target.value === "" ? null : Number(e.target.value),
                  }))
                }
                className="w-16 rounded-md border px-2 py-1 text-xs"
                placeholder="от"
              />
              <span className="text-muted-foreground">—</span>
              <input
                type="number"
                min={0}
                value={printSettings.maxQty ?? ""}
                onChange={(e) =>
                  setPrintSettings((prev) => ({
                    ...prev,
                    maxQty:
                      e.target.value === "" ? null : Number(e.target.value),
                  }))
                }
                className="w-16 rounded-md border px-2 py-1 text-xs"
                placeholder="до"
              />
            </div>

            {/* Кнопка печати — сразу открывает окно печати браузера */}
            <button
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 text-xs font-medium"
              onClick={() => window.print()}
              title="Печать плана"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="6 9 6 2 18 2 18 9"></polyline>
                <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                <rect x="6" y="14" width="12" height="8"></rect>
              </svg>
              Печать
            </button>
          </div>
        </div>

        {/* Таблицы — переключение по printSettings.tableMode */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-4">
          {hiddenGroupKeys.size > 0 && (
            <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <span>
                Скрыто из плана: <b>{hiddenGroupKeys.size}</b> групп(ы)
              </span>
              <button
                type="button"
                onClick={showAllGroups}
                className="ml-auto px-2 py-1 rounded-md border border-amber-300 bg-white hover:bg-amber-100 text-amber-900"
              >
                Показать все
              </button>
            </div>
          )}
          {showSingleTable ? (
            <div className="min-w-0">
              <PlanTable
                title="План"
                tasks={filteredTasks}
                profile={singleProfile!}
                onSettingsClick={() => setBeforeSettingsOpen(true)}
                emptyMessage="Нет данных"
                printSettings={printSettings}
                onHideGroup={hideGroup}
                isHidden={isGroupHidden}
              />
            </div>
          ) : printSettings.tableMode === "both" ? (
            <div className="grid grid-cols-2 gap-4 min-w-0">
              <div className="min-w-0">
                <PlanTable
                  title="План выдачи на участок"
                  tasks={filteredTasks}
                  profile={beforeProfile}
                  onSettingsClick={() => setBeforeSettingsOpen(true)}
                  emptyMessage="Нет данных"
                  printSettings={printSettings}
                  onHideGroup={hideGroup}
                  isHidden={isGroupHidden}
                />
              </div>
              <div className="min-w-0">
                <PlanTable
                  title="План сдачи с участка"
                  tasks={filteredTasks}
                  profile={afterProfile}
                  onSettingsClick={() => setAfterSettingsOpen(true)}
                  emptyMessage="Нет данных"
                  printSettings={printSettings}
                  onHideGroup={hideGroup}
                  isHidden={isGroupHidden}
                />
              </div>
            </div>
          ) : printSettings.tableMode === "before" ? (
            <div className="min-w-0">
              <PlanTable
                title="План выдачи на участок"
                tasks={filteredTasks}
                profile={beforeProfile}
                onSettingsClick={() => setBeforeSettingsOpen(true)}
                emptyMessage="Нет данных"
                printSettings={printSettings}
                onHideGroup={hideGroup}
                isHidden={isGroupHidden}
              />
            </div>
          ) : (
            <div className="min-w-0">
              <PlanTable
                title="План сдачи с участка"
                tasks={filteredTasks}
                profile={afterProfile}
                onSettingsClick={() => setAfterSettingsOpen(true)}
                emptyMessage="Нет данных"
                printSettings={printSettings}
                onHideGroup={hideGroup}
                isHidden={isGroupHidden}
              />
            </div>
          )}
        </div>

        <div className="flex justify-end p-4 border-t no-print">
          <button
            className="px-4 py-2 rounded-md border hover:bg-gray-50 text-sm"
            onClick={() => onOpenChange(false)}
          >
            Закрыть
          </button>
        </div>
      </div>

      {/* Before settings (or single table settings) */}
      {beforeSettingsOpen && (
        <GroupingSettingsModal
          sectionId={0}
          sectionName={sectionName}
          currentProfile={showSingleTable ? singleProfile! : beforeProfile}
          onClose={() => setBeforeSettingsOpen(false)}
          onApply={(newProfile) => {
            setBeforeSettingsOpen(false);
            if (showSingleTable) {
              setBeforeProfile(newProfile);
              saveProfile(`plan-before-group-profile-${sectionId}`, newProfile);
            } else {
              setBeforeProfile(newProfile);
              saveProfile(`plan-before-group-profile-${sectionId}`, newProfile);
            }
          }}
        />
      )}

      {/* After settings (only in dual table mode) */}
      {!showSingleTable && afterSettingsOpen && (
        <GroupingSettingsModal
          sectionId={0}
          sectionName={sectionName}
          currentProfile={afterProfile}
          onClose={() => setAfterSettingsOpen(false)}
          onApply={(newProfile) => {
            setAfterSettingsOpen(false);
            setAfterProfile(newProfile);
            saveProfile(`plan-after-group-profile-${sectionId}`, newProfile);
          }}
        />
      )}

      {/* Print preview — все настройки переданы из PlanModal */}
      {printSettingsOpen && (
        <PlanPrintPreviewModal
          sectionId={sectionId}
          sectionName={sectionName}
          onClose={() => setPrintSettingsOpen(false)}
          hasBefore={!showSingleTable}
          hasAfter={!showSingleTable}
          tasks={filteredTasks}
          beforeProfile={beforeProfile}
          afterProfile={afterProfile}
          singleProfile={singleProfile}
          showSingleTable={showSingleTable}
          settings={printSettings}
          hiddenGroupKeys={hiddenGroupKeys}
        />
      )}

      <AlertDialog open={!!presetToDelete} onOpenChange={(open) => !open && setPresetToDelete(null)}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить пресет?</AlertDialogTitle>
            <AlertDialogDescription>
              Пресет «{presetToDelete?.name}» будет удалён без возможности восстановления.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeletePreset}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

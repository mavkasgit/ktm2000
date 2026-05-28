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
import type { SectionBoardTask, RouteHistoryOp } from "@/shared/api/shopfloor";
import { groupTasksByProfile } from "../lib/groupTasksByProfile";
import { GroupingSettingsModal } from "./GroupingSettingsModal";
import { PRESET_PROFILES, type GroupingProfile } from "../lib/groupingProfiles";
import { renderIcon } from "@/shared/ui";


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

interface PlanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sectionId: number;
  sectionName: string;
  tasks: SectionBoardTask[];
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


// ---------------------------------------------------------------------------
// PlanTable — переиспользуемая таблица (issue / send)
// ---------------------------------------------------------------------------

interface PlanTableProps {
  title: string;
  tasks: SectionBoardTask[];
  profile: GroupingProfile;
  onSettingsClick: () => void;
  emptyMessage?: string;
}

function PlanTable({ title, tasks, profile, onSettingsClick, emptyMessage }: PlanTableProps) {
  const groups = useMemo(() => groupTasksByProfile(tasks, profile), [tasks, profile]);

  const totalQtyPlan = useMemo(
    () => groups.reduce((sum, g) => sum + g.totalQtyPlan, 0),
    [groups],
  );

  const totalIssued = useMemo(() => sumCache(groups, (t) => parseFloat(t.cache.issued_quantity)), [groups]);
  const totalTransferred = useMemo(() => sumCache(groups, (t) => parseFloat(t.cache.transferred_quantity)), [groups]);
  const totalDone = useMemo(() => groups.reduce((s, g) => s + g.totalQtyDone, 0), [groups]);
  const totalOrders = useMemo(() => groups.reduce((s, g) => s + g.tasks.length, 0), [groups]);

  const colSpan = 1 +
    (profile.criteria.includes("operationCode") ? 1 : 0) +
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
            <th className="text-left px-2 py-2 font-medium max-w-[120px] break-words">Артикул</th>
            {profile.criteria.includes("operationCode") && (
              <th className="text-left px-2 py-2 font-medium max-w-[140px] break-words">Операция</th>
            )}
            {profile.criteria.includes("outputKind") && (
              <th className="text-left px-2 py-2 font-medium">Цвет</th>
            )}
            {profile.criteria.includes("sourceRef") && (
              <th className="text-left px-2 py-2 font-medium">Заказ</th>
            )}
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap">План</th>
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap" style={{ minWidth: "60px" }}>Осталось<br/>выдать</th>
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Передано</th>
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Остаток</th>
            <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Заказов</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const task = group.tasks[0];
            const sig = task.signature;

            // Collect unique operations across all tasks in the group.
            // Deduplicate by operation_name to avoid showing duplicates like
            // "Выдача сырья • Выдача сырья" for combined profiles where different
            // branches have different operation_codes but the same operation_name.
            const uniqueOps = new Map<string, { code: string; icon?: string; iconColor?: string }>();
            for (const t of group.tasks) {
              const opName = t.signature.operation_name ?? "—";
              if (!uniqueOps.has(opName)) {
                uniqueOps.set(opName, {
                  code: t.signature.operation_code ?? "—",
                  icon: (t.signature as any).icon,
                  iconColor: (t.signature as any).icon_color,
                });
              }
            }

            return (
              <tr key={group.key} className="border-b hover:bg-gray-50">
                {/* Артикул */}
                <td className="px-2 py-2 max-w-[120px] break-words">
                  {task.product_sku}
                </td>

                {/* Операция */}
                {profile.criteria.includes("operationCode") && (
                  <td className="px-2 py-2 text-sm max-w-[140px] break-words">
                    {uniqueOps.size === 1 ? (
                      <div className="font-medium">{Array.from(uniqueOps.keys())[0]}</div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1 text-[10px]">
                        {Array.from(uniqueOps.entries()).map(([opName, op], i) => (
                          <React.Fragment key={i}>
                            {i > 0 && <span className="text-muted-foreground">•</span>}
                            <span
                              className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-gray-100"
                              style={{ color: op.iconColor || undefined }}
                              title={opName}
                            >
                              {op.icon && renderIcon(op.icon, "h-3 w-3")}
                              <span className="truncate max-w-[60px]">{opName}</span>
                            </span>
                          </React.Fragment>
                        ))}
                      </div>
                    )}
                    {sig.route_history?.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 mt-1 text-[10px]">
                        {sig.route_history.map((op: RouteHistoryOp, i: number) => (
                          <React.Fragment key={i}>
                            {i > 0 && <span className="text-muted-foreground">→</span>}
                            <span
                              className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-gray-100"
                              style={{ color: op.icon_color || undefined }}
                              title={op.operation_name}
                            >
                              {op.icon && renderIcon(op.icon, "h-3 w-3")}
                              <span className="truncate max-w-[60px]">{op.operation_name}</span>
                            </span>
                          </React.Fragment>
                        ))}
                      </div>
                    )}
                  </td>
                )}

                {/* Цвет */}
                {profile.criteria.includes("outputKind") && (
                  <td className="px-2 py-2 text-sm">{sig.output_kind ?? "—"}</td>
                )}

                {/* Заказ */}
                {profile.criteria.includes("sourceRef") && (
                  <td className="px-2 py-2 text-sm">{sig.source_ref ?? "—"}</td>
                )}

                {/* Количество */}
                <td className="px-2 py-2 text-right font-medium">
                  {group.totalQtyPlan.toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right">
                  {(group.totalQtyPlan - totalIssued >= 0 ? group.totalQtyPlan - sumCache([group], (t) => parseFloat(t.cache.issued_quantity)) : 0).toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right">
                  {sumCache([group], (t) => parseFloat(t.cache.transferred_quantity)).toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right text-blue-700 font-semibold">
                  {(group.totalQtyPlan - group.totalQtyDone).toFixed(0)}
                </td>

                {/* Кол-во заказов */}
                <td className="px-2 py-2 text-right text-muted-foreground">
                  {group.tasks.length}
                </td>
              </tr>
            );
          })}

          {/* Итого */}
          <tr className="border-t font-semibold bg-gray-50">
            <td colSpan={colSpan} className="px-2 py-2">Итого</td>
            <td className="px-2 py-2 text-right">{totalQtyPlan.toFixed(0)}</td>
            <td className="px-2 py-2 text-right">{(totalQtyPlan - totalIssued >= 0 ? totalQtyPlan - totalIssued : 0).toFixed(0)}</td>
            <td className="px-2 py-2 text-right">{totalTransferred.toFixed(0)}</td>
            <td className="px-2 py-2 text-right text-blue-700">{(totalQtyPlan - totalDone).toFixed(0)}</td>
            <td className="px-2 py-2 text-right text-muted-foreground">{totalOrders}</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  );
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
}: PlanModalProps) {
  const [beforeSettingsOpen, setBeforeSettingsOpen] = useState(false);
  const [afterSettingsOpen, setAfterSettingsOpen] = useState(false);

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
  }, [sectionId]);

  // Все задачи для плана
  const allTasks = useMemo(
    () => tasks,
    [tasks],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
      onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
    >
      <div className="bg-white rounded-lg shadow-xl w-[80vw] max-w-7xl max-h-[90vh] flex flex-col m-4" role="dialog" aria-modal>

        {/* Заголовок */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">План: {sectionName}</h2>
          <button
            className="text-muted-foreground hover:text-foreground text-2xl leading-none"
            onClick={() => onOpenChange(false)}
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        {/* Таблицы — две колонки: До / После */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-4">
          <div className="grid grid-cols-2 gap-4 min-w-0">
            <div className="min-w-0">
              <PlanTable
                title="До"
                tasks={allTasks}
                profile={beforeProfile}
                onSettingsClick={() => setBeforeSettingsOpen(true)}
                emptyMessage="Нет данных"
              />
            </div>
            <div className="min-w-0">
              <PlanTable
                title="После"
                tasks={allTasks}
                profile={afterProfile}
                onSettingsClick={() => setAfterSettingsOpen(true)}
                emptyMessage="Нет данных"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end p-4 border-t">
          <button
            className="px-4 py-2 rounded-md border hover:bg-gray-50 text-sm"
            onClick={() => onOpenChange(false)}
          >
            Закрыть
          </button>
        </div>
      </div>

      {/* Before settings */}
      {beforeSettingsOpen && (
        <GroupingSettingsModal
          sectionId={0}
          sectionName={sectionName}
          currentProfile={beforeProfile}
          onClose={() => setBeforeSettingsOpen(false)}
          onApply={(newProfile) => {
            setBeforeSettingsOpen(false);
            setBeforeProfile(newProfile);
            saveProfile(`plan-before-group-profile-${sectionId}`, newProfile);
          }}
        />
      )}

      {/* After settings */}
      {afterSettingsOpen && (
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
    </div>
  );
}

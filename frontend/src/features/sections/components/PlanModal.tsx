/**
 * components/PlanModal.tsx
 * =========================
 * Модальное окно просмотра плана для участка.
 *
 * Использует тот же groupTasksByProfile — консистентность с доской.
 */

import { useMemo, useState } from "react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { groupTasksByProfile } from "../lib/groupTasksByProfile";
import { GroupingSettingsModal } from "./GroupingSettingsModal";


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

interface PlanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sectionName: string;
  tasks: SectionBoardTask[];
  profile: GroupingProfile;
  onProfileChange?: (profile: GroupingProfile) => void;
}


// ---------------------------------------------------------------------------
// Компонент
// ---------------------------------------------------------------------------

export function PlanModal({
  open,
  onOpenChange,
  sectionName,
  tasks,
  profile,
  onProfileChange,
}: PlanModalProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  const isWaitingStatus = (status: string) => status === "pending" || status === "waiting_previous" || status === "blocked";

  // Фильтруем завершённые задачи (остаток = 0)
  const activeTasks = useMemo(
    () => tasks.filter((t) => {
      const planned = parseFloat(t.planned_quantity);
      const completed = parseFloat(t.cache.completed_quantity);
      return planned - completed > 0 && !isWaitingStatus(t.status);
    }),
    [tasks],
  );

  // Ожидаемые задачи
  const waitingTasks = useMemo(
    () => tasks.filter((t) => isWaitingStatus(t.status)),
    [tasks],
  );

  const activeGroups = useMemo(
    () => groupTasksByProfile(activeTasks, profile),
    [activeTasks, profile],
  );

  const waitingGroups = useMemo(
    () => groupTasksByProfile(waitingTasks, profile),
    [waitingTasks, profile],
  );

  const activeTotal = useMemo(
    () => activeGroups.reduce((sum, g) => sum + g.totalQtyPlan, 0),
    [activeGroups],
  );

  const waitingTotal = useMemo(
    () => waitingGroups.reduce((sum, g) => sum + g.totalQtyPlan, 0),
    [waitingGroups],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
      onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
    >
      <div className="bg-white rounded-lg shadow-xl w-fit max-h-[90vh] flex flex-col m-4" role="dialog" aria-modal>

        {/* Заголовок */}
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h2 className="text-lg font-semibold">План: {sectionName}</h2>
            <p className="text-sm text-muted-foreground">
              Группировка:{" "}
              <button
                className="font-semibold text-blue-600 hover:text-blue-800 underline"
                onClick={() => setSettingsOpen(true)}
              >
                {profile.name}
              </button>
            </p>
          </div>
          <button
            className="text-muted-foreground hover:text-foreground text-2xl leading-none"
            onClick={() => onOpenChange(false)}
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        {/* Таблица плана */}
        <div className="flex-1 overflow-auto p-4">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b">
                <th className="text-left px-2 py-2 font-medium">Артикул</th>
                {profile.criteria.includes("operationCode") && (
                  <th className="text-left px-2 py-2 font-medium">Операция</th>
                )}
                {profile.criteria.includes("outputKind") && (
                  <th className="text-left px-2 py-2 font-medium">Цвет</th>
                )}
                {profile.criteria.includes("sourceRef") && (
                  <th className="text-left px-2 py-2 font-medium">Заказ</th>
                )}
                <th className="text-right px-2 py-2 font-medium">План</th>
                <th className="text-right px-2 py-2 font-medium" style={{ minWidth: "60px" }}>Осталось<br/>выдать</th>
                <th className="text-right px-2 py-2 font-medium">Передано</th>
                <th className="text-right px-2 py-2 font-medium">Остаток</th>
                <th className="text-right px-2 py-2 font-medium">Заказов</th>
              </tr>
            </thead>
            <tbody>
              {/* Активные задачи */}
              {activeGroups.map((group) => {
                const sig = group.tasks[0].signature;
                const isTransforming = sig.input_sku !== sig.output_sku;

                return (
                  <tr key={group.key} className="border-b hover:bg-gray-50">
                    {/* Артикул */}
                    <td className="px-2 py-2">
                      {isTransforming ? (
                        <span className="flex items-center gap-1 text-xs">
                          <span className="text-muted-foreground">{sig.input_sku}</span>
                          <span className="text-blue-500">→</span>
                          <span className="font-semibold">{sig.output_sku}</span>
                        </span>
                      ) : (
                        sig.output_sku
                      )}
                    </td>

                    {/* Операция — все завершённые значимые операции в группе */}
                    {profile.criteria.includes("operationCode") && (
                      <td className="px-2 py-2 text-sm">
                        {(() => {
                          const completedOps = new Set<string>();
                          for (const t of group.tasks) {
                            if (parseFloat(t.cache.completed_quantity) > 0 && t.signature.is_significant && t.operation_name) {
                              completedOps.add(t.operation_name);
                            }
                          }
                          return completedOps.size > 0
                            ? Array.from(completedOps).join(", ")
                            : "—";
                        })()}
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
                      {(group.totalQtyPlan - group.tasks.reduce((s, t) => s + parseFloat(t.cache.issued_quantity), 0)).toFixed(0)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {group.tasks.reduce((s, t) => s + parseFloat(t.cache.transferred_quantity), 0).toFixed(0)}
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

              {/* Итого активные */}
              <tr className="border-t font-semibold bg-gray-50">
                <td colSpan={
                  1 +
                  (profile.criteria.includes("operationCode") ? 1 : 0) +
                  (profile.criteria.includes("outputKind") ? 1 : 0) +
                  (profile.criteria.includes("sourceRef") ? 1 : 0)
                } className="px-2 py-2">
                  Итого
                </td>
                <td className="px-2 py-2 text-right">
                  {activeTotal.toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right">
                  {(activeTotal - activeGroups.reduce((s, g) => s + g.tasks.reduce((ss, t) => ss + parseFloat(t.cache.issued_quantity), 0), 0)).toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right">
                  {activeGroups.reduce((s, g) => s + g.tasks.reduce((ss, t) => ss + parseFloat(t.cache.transferred_quantity), 0), 0).toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right text-blue-700">
                  {(activeTotal - activeGroups.reduce((s, g) => s + g.totalQtyDone, 0)).toFixed(0)}
                </td>
                <td className="px-2 py-2 text-right text-muted-foreground">
                  {activeGroups.reduce((sum, g) => sum + g.tasks.length, 0)}
                </td>
              </tr>

              {/* Ожидаемые задачи */}
              {waitingGroups.length > 0 && (
                <>
                  <tr><td colSpan={99} className="p-3"></td></tr>
                  <tr className="border-b-2 border-orange-200 bg-orange-50">
                    <td colSpan={99} className="px-2 py-2 font-semibold text-orange-800">
                      Ожидают начала — {waitingGroups.length} групп
                    </td>
                  </tr>
                  {waitingGroups.map((group) => {
                    const sig = group.tasks[0].signature;
                    const isTransforming = sig.input_sku !== sig.output_sku;

                    return (
                      <tr key={group.key} className="border-b bg-orange-50/50">
                        <td className="px-2 py-2">
                          {isTransforming ? (
                            <span className="flex items-center gap-1 text-xs">
                              <span className="text-muted-foreground">{sig.input_sku}</span>
                              <span className="text-orange-400">→</span>
                              <span className="font-semibold">{sig.output_sku}</span>
                            </span>
                          ) : (
                            sig.output_sku
                          )}
                        </td>
                        {profile.criteria.includes("operationCode") && (
                          <td className="px-2 py-2 text-sm text-muted-foreground">—</td>
                        )}
                        {profile.criteria.includes("outputKind") && (
                          <td className="px-2 py-2 text-sm">{sig.output_kind ?? "—"}</td>
                        )}
                        {profile.criteria.includes("sourceRef") && (
                          <td className="px-2 py-2 text-sm">{sig.source_ref ?? "—"}</td>
                        )}
                        <td className="px-2 py-2 text-right font-medium">
                          {group.totalQtyPlan.toFixed(0)}
                        </td>
                        <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                        <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                        <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                        <td className="px-2 py-2 text-right text-muted-foreground">
                          {group.tasks.length}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="border-t font-semibold bg-orange-100">
                    <td colSpan={
                      1 +
                      (profile.criteria.includes("operationCode") ? 1 : 0) +
                      (profile.criteria.includes("outputKind") ? 1 : 0) +
                      (profile.criteria.includes("sourceRef") ? 1 : 0)
                    } className="px-2 py-2">
                      Итого ожидают
                    </td>
                    <td className="px-2 py-2 text-right">
                      {waitingTotal.toFixed(0)}
                    </td>
                    <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                    <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                    <td className="px-2 py-2 text-right text-muted-foreground">—</td>
                    <td className="px-2 py-2 text-right text-muted-foreground">
                      {waitingGroups.reduce((sum, g) => sum + g.tasks.length, 0)}
                    </td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
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

      {/* Grouping settings */}
      {settingsOpen && (
        <GroupingSettingsModal
          sectionId={0}
          sectionName={sectionName}
          currentProfile={profile}
          onClose={() => setSettingsOpen(false)}
          onApply={(newProfile) => {
            setSettingsOpen(false);
            onProfileChange?.(newProfile);
          }}
        />
      )}
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";

import type { DailyPlanCompositionItem, DailyPlanSummary } from "@/shared/api/shopfloor";
import { Button, DatePicker } from "@/shared/ui";

type DailyPlansPanelProps = {
  plans: DailyPlanSummary[];
  selectedPlanIds: Set<number>;
  onTogglePlan: (planId: number) => void;
  onClearPlans: () => void;
  onCreatePlan?: (planDate: string) => void;
  onOpenPlans?: () => void;
  readOnly?: boolean;
  isLoading?: boolean;
  compositionItems?: DailyPlanCompositionItem[];
  onRevokeItem?: (planId: number, workTaskId: number) => void;
  isRevoking?: boolean;
  isCreating?: boolean;
  createErrorMessage?: string | null;
};

function localToday(): string {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
export function DailyPlansPanel({
  plans,
  selectedPlanIds,
  onTogglePlan,
  onClearPlans,
  onCreatePlan,
  onOpenPlans,
  readOnly = false,
  isLoading = false,
  compositionItems = [],
  onRevokeItem,
  isRevoking = false,
  isCreating = false,
  createErrorMessage = null,
}: DailyPlansPanelProps) {
  const [creating, setCreating] = useState(false);
  const [planDate, setPlanDate] = useState(localToday);

  const planNumber = useMemo(() => {
    const sameDatePlans = plans
      .filter((plan) => plan.plan_date === planDate)
      .sort((left, right) => left.created_at.localeCompare(right.created_at));
    return sameDatePlans.length + 1;
  }, [planDate, plans]);

  const startCreating = () => {
    if (!onCreatePlan) return;
    setPlanDate(localToday());
    setCreating(true);
  };

  useEffect(() => {
    if (!isCreating && !createErrorMessage) setCreating(false);
  }, [createErrorMessage, isCreating]);
  const cancelCreating = () => {
    setCreating(false);
    setPlanDate(localToday());
  };

  return (
    <aside className="space-y-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="group min-w-0 flex-1 justify-center rounded-md px-1 py-0.5 text-center transition-colors hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          onClick={onOpenPlans}
          disabled={!onOpenPlans}
          aria-label={readOnly ? "Открыть дневные планы" : "Вернуться к заданиям"}
        >
          <h2 className="flex items-center justify-center gap-1.5 whitespace-nowrap text-sm font-semibold text-blue-700 underline decoration-blue-300 underline-offset-4 group-hover:decoration-blue-600">
            {readOnly ? "Дневные планы" : "Задания"}
            <span
              aria-hidden="true"
              className={`text-base font-bold text-black transition-transform ${readOnly ? "group-hover:translate-x-0.5" : "group-hover:-translate-x-0.5"}`}
            >
              {readOnly ? "→" : "←"}
            </span>
          </h2>
        </button>
        {!readOnly && onCreatePlan && !creating && (
          <Button size="sm" onClick={startCreating}>Создать план</Button>
        )}
        {!readOnly && creating && (
          <Button size="sm" variant="outline" onClick={cancelCreating} disabled={isCreating}>
            Отмена
          </Button>
        )}
      </div>

      {!readOnly && creating && (
        <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50/60 p-2.5">
          <DatePicker
            value={planDate}
            onChange={setPlanDate}
            label="Дата плана"
            disabled={isCreating}
            className="w-full"
          />
          <div className="flex items-center justify-between gap-2 text-xs text-slate-700">
            <span>Номер плана на дату</span>
            <span className="font-semibold tabular-nums">№{planNumber}</span>
          </div>
          {createErrorMessage && <p className="text-xs text-destructive">{createErrorMessage}</p>}
          <Button size="sm" className="w-full" disabled={isCreating} onClick={() => onCreatePlan?.(planDate)}>
            {isCreating ? "Создание…" : "Подтвердить"}
          </Button>
        </div>
      )}

      <Button
        variant={selectedPlanIds.size === 0 ? "default" : "outline"}
        size="sm"
        className="w-full justify-start"
        onClick={onClearPlans}
      >
        Все задания участка
      </Button>

      <div className="space-y-1.5">
        <div className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Недавние планы
        </div>
        {isLoading ? (
          <p className="px-1 py-2 text-xs text-slate-500">Загрузка планов…</p>
        ) : plans.length === 0 ? (
          <p className="px-1 py-2 text-xs text-slate-500">Планов пока нет</p>
        ) : plans.map((plan) => {
          const selected = selectedPlanIds.has(plan.id);
          const sameDatePlans = plans
            .filter((item) => item.plan_date === plan.plan_date)
            .sort((left, right) => left.created_at.localeCompare(right.created_at));
          const number = sameDatePlans.findIndex((item) => item.id === plan.id) + 1;
          return (
            <button
              key={plan.id}
              type="button"
              aria-pressed={selected}
              className={`w-full rounded-md border px-2.5 py-2 text-left transition-colors ${
                selected
                  ? "border-blue-500 bg-blue-50 text-blue-900"
                  : "border-slate-200 bg-white text-slate-800 hover:border-blue-300 hover:bg-slate-50"
              }`}
              onClick={() => onTogglePlan(plan.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">План №{number} · {plan.plan_date}</span>
                <span className="text-xs font-semibold tabular-nums">{plan.progress_percent}%</span>
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {plan.item_count} заданий
              </div>
            </button>
          );
        })}
      </div>
      {!readOnly && selectedPlanIds.size > 0 && (
        <div className="space-y-2 border-t border-slate-100 pt-3">
          <div className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Состав выбранных планов
          </div>
          {compositionItems.length === 0 ? (
            <p className="px-1 text-xs text-slate-500">В выбранных планах нет заданий.</p>
          ) : (
            <div className="max-h-64 space-y-1 overflow-y-auto">
              {compositionItems.map((item) => (
                <div key={`${item.daily_plan_id}-${item.work_task_id}`} className="flex items-center gap-2 rounded border px-2 py-1.5">
                  <span className="min-w-0 flex-1 truncate text-xs" title={item.task.display_sku || item.task.product_sku}>
                    {item.task.display_sku || item.task.product_sku} · план {item.daily_plan_id}
                  </span>
                  {onRevokeItem && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs text-red-700 hover:text-red-800"
                      disabled={isRevoking}
                      onClick={() => onRevokeItem(item.daily_plan_id, item.work_task_id)}
                    >
                      Отозвать
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

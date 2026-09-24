import { Button } from "@/shared/ui";
import type { DailyPlanCompositionItem, DailyPlanSummary } from "@/shared/api/shopfloor";

type DailyPlansPanelProps = {
  plans: DailyPlanSummary[];
  selectedPlanIds: Set<number>;
  onTogglePlan: (planId: number) => void;
  onClearPlans: () => void;
  onCreatePlan?: () => void;
  readOnly?: boolean;
  isLoading?: boolean;
  compositionItems?: DailyPlanCompositionItem[];
  onRevokeItem?: (planId: number, workTaskId: number) => void;
  isRevoking?: boolean;
};

export function DailyPlansPanel({
  plans,
  selectedPlanIds,
  onTogglePlan,
  onClearPlans,
  onCreatePlan,
  readOnly = false,
  isLoading = false,
  compositionItems = [],
  onRevokeItem,
  isRevoking = false,
}: DailyPlansPanelProps) {
  return (
    <aside className="space-y-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Дневные планы</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {readOnly ? "Фильтр заданий участка" : "Выбор планов для печати"}
          </p>
        </div>
        {!readOnly && onCreatePlan && (
          <Button size="sm" onClick={onCreatePlan}>Создать план</Button>
        )}
      </div>

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
          const createdAt = new Date(plan.created_at);
          const createdTime = Number.isNaN(createdAt.getTime())
            ? ""
            : createdAt.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
          const dateHasMultiplePlans = plans.filter((item) => item.plan_date === plan.plan_date).length > 1;
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
                <span className="text-sm font-medium">{plan.plan_date}</span>
                <span className="text-xs font-semibold tabular-nums">{plan.progress_percent}%</span>
              </div>
              <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-500">
                <span>{plan.item_count} заданий</span>
                {dateHasMultiplePlans && <span>{createdTime}</span>}
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

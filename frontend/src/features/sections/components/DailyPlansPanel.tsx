import { useEffect, useMemo, useState } from "react";

import type { DailyPlanSummary } from "@/shared/api/shopfloor";
import { Button, DatePicker, Input, formatDateRu } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";

import type { DailyPlanListEntry } from "../lib/dailyPlanList";
import { PLAN_SHOW_MORE_STEP, buildPlanEntries, buildPlanListBlocks } from "../lib/dailyPlanList";

type DailyPlansPanelProps = {
  plans: DailyPlanSummary[];
  selectedPlanIds: Set<number>;
  onSelectPlan: (planId: number) => void;
  onTogglePlan: (planId: number) => void;
  onClearPlans: () => void;
  onCreatePlan?: (planDate: string) => void;
  onOpenPlans?: () => void;
  /**
   * Куда ведёт кнопка-ссылка в заголовке: `true` — на вкладку
   * «Дневные планы», `false` — обратно на «Задания». Раньше эту
   * подпись рисовал `readOnly`, тем же пропсом, что прячет форму
   * создания, из-за чего переход на план пропал: сняли `readOnly`,
   * чтобы открыть форму, и подпись стала «Задания ←» в обеих
   * вкладках.
   */
  opensPlans?: boolean;
  isLoading?: boolean;
  isCreating?: boolean;
  createErrorMessage?: string | null;
  selectedTaskCount?: number;
  onCreateModeChange?: (creating: boolean) => void;
};

function localToday(): string {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
export function DailyPlansPanel({
  plans,
  selectedPlanIds,
  onSelectPlan,
  onTogglePlan,
  onClearPlans,
  onCreatePlan,
  onOpenPlans,
  opensPlans = false,
  isLoading = false,
  isCreating = false,
  createErrorMessage = null,
  selectedTaskCount = 0,
  onCreateModeChange,
}: DailyPlansPanelProps) {
  const [creating, setCreating] = useState(false);
  const [planDate, setPlanDate] = useState(localToday);
  const [search, setSearch] = useState("");
  const [extraVisible, setExtraVisible] = useState(0);

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
  useEffect(() => {
    onCreateModeChange?.(creating);
  }, [creating, onCreateModeChange]);
  const cancelCreating = () => {
    setCreating(false);
    setPlanDate(localToday());
  };
  const hasSelectedTasks = selectedTaskCount > 0;
  const hasActivePlans = selectedPlanIds.size > 0;

  // Список планов: выбранные всплывают наверх, остальные по дате,
  // выбранные вне поисковой строки — в хвосте, чтобы доска не
  // показывала задания плана, которого в панели не видно.
  const { selectedEntries, otherEntries, outOfSearchEntries, hiddenCount } = useMemo(() => {
    const blocks = buildPlanListBlocks(
      buildPlanEntries(plans),
      selectedPlanIds,
      search,
      extraVisible,
    );
    return {
      selectedEntries: blocks.selected,
      otherEntries: blocks.others,
      outOfSearchEntries: blocks.selectedOutOfSearch,
      hiddenCount: blocks.hiddenCount,
    };
  }, [extraVisible, plans, search, selectedPlanIds]);

  return (
    <aside className="space-y-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="group min-w-0 flex-1 justify-center rounded-md px-1 py-0.5 text-center transition-colors hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          onClick={onOpenPlans}
          disabled={!onOpenPlans || creating}
          aria-label={opensPlans ? "Открыть дневные планы" : "Вернуться к заданиям"}
        >
          <h2 className="flex items-center justify-center gap-1.5 whitespace-nowrap text-sm font-semibold text-blue-700 underline decoration-blue-300 underline-offset-4 group-hover:decoration-blue-600">
            {opensPlans ? "Дневные планы" : "Задания"}
            <span
              aria-hidden="true"
              className={`text-base font-bold text-black transition-transform ${opensPlans ? "group-hover:translate-x-0.5" : "group-hover:-translate-x-0.5"}`}
            >
              {opensPlans ? "→" : "←"}
            </span>
          </h2>
        </button>
        {onCreatePlan && !creating && (
          <Button size="sm" onClick={startCreating}>
            Создать план
          </Button>
        )}
        {creating && (
          <Button size="sm" variant="outline" onClick={cancelCreating} disabled={isCreating}>
            Отмена
          </Button>
        )}
      </div>

      {creating && (
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
          <div className="text-xs text-slate-700">
            {hasSelectedTasks ? `Выбрано заданий: ${selectedTaskCount}` : "Теперь выделите задания в таблице"}
          </div>
          {createErrorMessage && <p className="text-xs text-destructive">{createErrorMessage}</p>}
          <Button
            size="sm"
            className="w-full"
            disabled={isCreating || !hasSelectedTasks}
            title={hasSelectedTasks ? "Создать дневной план" : "Сначала выделите задания"}
            onClick={() => onCreatePlan?.(planDate)}
          >
            {isCreating ? "Создание…" : "Подтвердить"}
          </Button>
        </div>
      )}

      <div className="flex items-stretch gap-1.5">
        <Button
          variant={selectedPlanIds.size === 0 ? "default" : "outline"}
          size="sm"
          className="min-w-0 flex-1 justify-start"
          onClick={onClearPlans}
        >
          <span className="truncate">Все задания участка</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "shrink-0 px-2.5",
            hasActivePlans &&
              "border-black bg-black text-white hover:bg-black/90 hover:text-white",
          )}
          onClick={onClearPlans}
          disabled={selectedPlanIds.size === 0}
          title="Выключить все планы"
          aria-label="Выключить все планы"
        >
          <span
            aria-hidden="true"
            className={`text-base leading-none ${hasActivePlans ? "text-white" : "text-slate-500"}`}
          >
            ✕
          </span>
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Недавние планы
        </div>
        {isLoading ? (
          <p className="px-1 py-2 text-xs text-slate-500">Загрузка планов…</p>
        ) : plans.length === 0 ? (
          <p className="px-1 py-2 text-xs text-slate-500">Планов пока нет</p>
        ) : (
          <>
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setExtraVisible(0);
              }}
              aria-label="Поиск дневных планов"
              placeholder="Поиск: дата или №"
              className="h-8 text-xs"
            />
            <div className="max-h-96 space-y-1.5 overflow-y-auto pr-0.5">
              {selectedEntries.length > 0 && (
                <>
                  <PlanGroupTitle>Выбрано ({selectedEntries.length})</PlanGroupTitle>
                  {selectedEntries.map((entry) => (
                    <PlanCard
                      key={entry.plan.id}
                      entry={entry}
                      selected={true}
                      onlySelected={selectedPlanIds.size === 1}
                      onSelectPlan={onSelectPlan}
                      onTogglePlan={onTogglePlan}
                    />
                  ))}
                </>
              )}
              {otherEntries.map((entry) => (
                <PlanCard
                  key={entry.plan.id}
                  entry={entry}
                  selected={false}
                  onlySelected={false}
                  onSelectPlan={onSelectPlan}
                  onTogglePlan={onTogglePlan}
                />
              ))}
              {otherEntries.length === 0 && selectedEntries.length === 0 && (
                <p className="px-1 py-2 text-xs text-slate-500">Ничего не найдено</p>
              )}
              {outOfSearchEntries.length > 0 && (
                <>
                  <PlanGroupTitle>
                    Не найдено среди выбранных ({outOfSearchEntries.length})
                  </PlanGroupTitle>
                  {outOfSearchEntries.map((entry) => (
                    <PlanCard
                      key={entry.plan.id}
                      entry={entry}
                      selected={true}
                      onlySelected={selectedPlanIds.size === 1}
                      onSelectPlan={onSelectPlan}
                      onTogglePlan={onTogglePlan}
                    />
                  ))}
                </>
              )}
              {hiddenCount > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => setExtraVisible((value) => value + PLAN_SHOW_MORE_STEP)}
                >
                  Показать ещё
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

type PlanCardProps = {
  entry: DailyPlanListEntry;
  selected: boolean;
  onlySelected: boolean;
  onSelectPlan: (planId: number) => void;
  onTogglePlan: (planId: number) => void;
};

function PlanCard({ entry, selected, onlySelected, onSelectPlan, onTogglePlan }: PlanCardProps) {
  const { plan, number } = entry;
  return (
    <div
      className={`flex items-stretch overflow-hidden rounded-md border transition-colors ${
        selected
          ? "border-blue-500 bg-blue-50 text-blue-900"
          : "border-slate-200 bg-white text-slate-800 hover:border-blue-300 hover:bg-slate-50"
      }`}
    >
      <button
        type="button"
        role="checkbox"
        aria-checked={selected}
        onClick={() => onTogglePlan(plan.id)}
        title={selected ? "Убрать план из выбранных" : "Добавить план к выбранным"}
        className="flex shrink-0 items-center px-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      >
        <span
          aria-hidden="true"
          className={`flex h-4 w-4 items-center justify-center rounded-[4px] border text-[11px] leading-none ${
            selected ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white"
          }`}
        >
          {selected ? "✓" : ""}
        </span>
      </button>
      <button
        type="button"
        data-plan-select
        aria-pressed={onlySelected}
        onClick={() => onSelectPlan(plan.id)}
        title="Показать только этот план"
        className="min-w-0 flex-1 py-2 pr-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">
            План №{number} · {formatDateRu(plan.plan_date)}
          </span>
          <span className="shrink-0 text-xs font-semibold tabular-nums">{plan.progress_percent}%</span>
        </div>
        <div className="mt-1 text-xs text-slate-500">{plan.item_count} заданий</div>
      </button>
    </div>
  );
}

function PlanGroupTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
      {children}
    </div>
  );
}

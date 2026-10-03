import { useEffect, useMemo, useState } from "react";

import type { DailyPlanSummary } from "@/shared/api/shopfloor";
import { Button, DatePicker, Input, formatDateRu } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";

import type { DailyPlanListEntry } from "../lib/dailyPlanList";
import { PLAN_SHOW_MORE_STEP, buildPlanEntries, buildPlanList } from "../lib/dailyPlanList";

/**
 * Панель дневных планов: заголовок с переходом на «Задания», форма создания,
 * поиск и потолок видимых карточек.
 *
 * Выбор план не переставляет: список всегда идёт по дате, выбранная карточка
 * помечается на месте, а ярлыки выбранных собираются в полосу «Выбрано» над
 * списком (там же снимаются). Раньше выбранное всплывало отдельным блоком
 * наверх, и карточка перескакивала через пол-панели на каждый клик.
 *
 * Высота — от экрана (`lg:h-[calc(100vh-2rem)]`), а не от колонки грида: раньше
 * список обрывался на `max-h-96` (384 px), а когда панель растянули до колонки,
 * колонку задавала доска — и на пустой доске панель сжималась до высоты пары
 * карточек, а на длинной уезжала ниже экрана. Потолок карточек выведен отсюда
 * же: восемь штук помещаются вместе с кнопкой «Показать ещё».
 */
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
    // Создание идёт по заданиям участка, а не по составу выбранного плана:
    // с оставленным фильтром доска показывала бы состав прежнего плана,
    // а кандидатов нового — нет.
    onClearPlans();
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

  // Список планов — всегда по дате: выбор его не переставляет. Выбранные
  // планы живут ярлыками в полосе «Выбрано» над списком, поэтому выбранный
  // план виден и когда его отсеял поиск, и когда он за потолком карточек.
  const { visibleEntries, selectedEntries, hiddenCount } = useMemo(() => {
    const entries = buildPlanEntries(plans);
    const list = buildPlanList(entries, search, extraVisible);
    return {
      visibleEntries: list.visible,
      selectedEntries: entries.filter((entry) => selectedPlanIds.has(entry.plan.id)),
      hiddenCount: list.hiddenCount,
    };
  }, [extraVisible, plans, search, selectedPlanIds]);

  return (
    <aside className="flex flex-col space-y-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:h-[calc(100vh-2rem)]">
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

      {/* Полоса выбранных: ярлык на каждый выбранный план. Список ниже порядок
          не меняет — выбранная карточка помечается на месте, а её ярлык живёт
          здесь. Поэтому выбранный план виден и когда его отсеял поиск, и когда
          он за потолком карточек. Высота полосы анимируется, чтобы список под
          ней сдвигался плавно. */}
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-300 ease-out",
          hasActivePlans ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          {hasActivePlans && (
            <div className="space-y-1 rounded-md border border-blue-200 bg-blue-50/60 p-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Выбрано ({selectedEntries.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {selectedEntries.map((entry) => (
                  <span
                    key={entry.plan.id}
                    className="inline-flex items-center gap-1 rounded-full border border-blue-300 bg-white px-2 py-0.5 text-[11px] text-blue-900"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectPlan(entry.plan.id)}
                      title="Показать только этот план"
                      className="max-w-[9rem] truncate"
                    >
                      План №{entry.number} · {formatDateRu(entry.plan.plan_date)}
                    </button>
                    <button
                      type="button"
                      onClick={() => onTogglePlan(entry.plan.id)}
                      aria-label="Убрать план из выбранных"
                      title="Убрать план из выбранных"
                      className="text-blue-700 hover:text-blue-900"
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col space-y-1.5">
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
            {/* Список занимает остаток панели и прокручивается сам: кнопка
                «Показать ещё» внутри него уезжала под последнюю карточку, и
                мастер её просто не видел — а она и есть весь смысл потолка.
                `min-h-0` обязателен, иначе flex-ребёнок не даёт прокрутке ужать
                список. */}
            <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-0.5">
              {visibleEntries.map((entry) => {
                const selected = selectedPlanIds.has(entry.plan.id);
                return (
                  <PlanCard
                    key={entry.plan.id}
                    entry={entry}
                    selected={selected}
                    onlySelected={selected && selectedPlanIds.size === 1}
                    onSelectPlan={onSelectPlan}
                    onTogglePlan={onTogglePlan}
                  />
                );
              })}
              {visibleEntries.length === 0 && (
                <p className="px-1 py-2 text-xs text-slate-500">Ничего не найдено</p>
              )}
            </div>
            {hiddenCount > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => setExtraVisible((value) => value + PLAN_SHOW_MORE_STEP)}
              >
                Показать ещё
              </Button>
            )}
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
        <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
          <span>{plan.item_count} заданий</span>
          {selected && <span className="font-semibold text-blue-700">· выбрано</span>}
        </div>
      </button>
    </div>
  );
}

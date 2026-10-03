import { describe, expect, it } from "vitest";
import type { DailyPlanSummary } from "@/shared/api/shopfloor";
import { buildPlanEntries, buildPlanList, planMatchesQuery } from "./dailyPlanList";

function makePlan(overrides: Partial<DailyPlanSummary> = {}): DailyPlanSummary {
  return {
    id: 1,
    section_id: 7,
    plan_date: "2026-09-26",
    created_at: "2026-09-26T08:00:00",
    created_by: 3,
    item_count: 4,
    progress_percent: 50,
    ...overrides,
  };
}

/** count планов одной даты: план №k создан на k-й минуте после 08:00. */
function planSeries(count: number, planDate = "2026-09-26"): DailyPlanSummary[] {
  return Array.from({ length: count }, (_, index) =>
    makePlan({
      id: index + 1,
      plan_date: planDate,
      created_at: `${planDate}T08:${String(index).padStart(2, "0")}:00`,
    }),
  );
}

/** Порядок бэкенда: `plan_date DESC, created_at DESC` — свежие сверху. */
function backendOrder(plans: DailyPlanSummary[]): DailyPlanSummary[] {
  return [...plans].reverse();
}

function planIds(entries: { plan: DailyPlanSummary }[]): number[] {
  return entries.map((entry) => entry.plan.id);
}

function numbers(entries: { number: number }[]): number[] {
  return entries.map((entry) => entry.number);
}

function matchingIds(plans: DailyPlanSummary[], query: string): number[] {
  return planIds(buildPlanEntries(plans).filter((entry) => planMatchesQuery(entry, query)));
}

// Панель разбирает запрос. id 1–3 — 26.09 (№1, №2, №3), 4–5 — 03.10
// (№1, №2), 6 — 26.10 (№1).
const SEARCH_PLANS: DailyPlanSummary[] = [
  makePlan({ id: 1, plan_date: "2026-09-26", created_at: "2026-09-26T08:00:00" }),
  makePlan({ id: 2, plan_date: "2026-09-26", created_at: "2026-09-26T09:00:00" }),
  makePlan({ id: 3, plan_date: "2026-09-26", created_at: "2026-09-26T10:00:00" }),
  makePlan({ id: 4, plan_date: "2026-10-03", created_at: "2026-10-03T08:00:00" }),
  makePlan({ id: 5, plan_date: "2026-10-03", created_at: "2026-10-03T09:00:00" }),
  makePlan({ id: 6, plan_date: "2026-10-26", created_at: "2026-10-26T08:00:00" }),
];

// ---------------------------------------------------------------------------
// buildPlanEntries
// ---------------------------------------------------------------------------

describe("buildPlanEntries", () => {
  it("нумерует по порядку created_at внутри даты, даже если планы пришли вперемешку", () => {
    const entries = buildPlanEntries([
      makePlan({ id: 30, created_at: "2026-09-26T10:00:00" }),
      makePlan({ id: 10, created_at: "2026-09-26T08:00:00" }),
      makePlan({ id: 20, created_at: "2026-09-26T09:00:00" }),
    ]);

    const byId = new Map(entries.map((entry) => [entry.plan.id, entry.number]));
    expect(byId.get(10)).toBe(1);
    expect(byId.get(20)).toBe(2);
    expect(byId.get(30)).toBe(3);
  });

  it("разные даты нумеруются независимо с 1", () => {
    const entries = buildPlanEntries([
      makePlan({ id: 1, plan_date: "2026-09-26", created_at: "2026-09-26T08:00:00" }),
      makePlan({ id: 2, plan_date: "2026-09-25", created_at: "2026-09-25T08:00:00" }),
      makePlan({ id: 3, plan_date: "2026-09-26", created_at: "2026-09-26T09:00:00" }),
      makePlan({ id: 4, plan_date: "2026-09-25", created_at: "2026-09-25T09:00:00" }),
    ]);

    const byId = new Map(entries.map((entry) => [entry.plan.id, entry.number]));
    expect(byId.get(1)).toBe(1);
    expect(byId.get(3)).toBe(2);
    expect(byId.get(2)).toBe(1);
    expect(byId.get(4)).toBe(2);
  });

  it("номер считается по полному списку: отсечение поздних планов не перенумеровывает видимые", () => {
    const plans = backendOrder(planSeries(12));
    const entries = buildPlanEntries(plans);

    // Без поиска потолок — 8 карточек из 12; номера остаются 12…5.
    const capped = buildPlanList(entries, "", 0);
    expect(numbers(capped.visible)).toEqual([12, 11, 10, 9, 8, 7, 6, 5]);
    expect(capped.hiddenCount).toBe(4);

    // Раскрытие показывает добавленные карточки с их настоящими номерами,
    // а не с «№1» и «№2» заново.
    const expanded = buildPlanList(entries, "", 20);
    expect(numbers(expanded.visible)).toEqual([12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
    expect(expanded.hiddenCount).toBe(0);
  });

  it("не мутирует и не переставляет входной массив", () => {
    const plans = backendOrder(planSeries(4));
    const snapshot = plans.map((plan) => plan.id);

    const entries = buildPlanEntries(plans);

    expect(plans.map((plan) => plan.id)).toEqual(snapshot);
    expect(planIds(entries)).toEqual(snapshot);
  });
});

// ---------------------------------------------------------------------------
// planMatchesQuery
// ---------------------------------------------------------------------------

describe("planMatchesQuery", () => {
  it("«26» находит 26-е число месяца, а не 26-й план", () => {
    expect(matchingIds(SEARCH_PLANS, "26")).toEqual([1, 2, 3, 6]);
  });

  it("«26.09» и «2026-09-26» — один и тот же день", () => {
    const shortForm = matchingIds(SEARCH_PLANS, "26.09");
    const fullForm = matchingIds(SEARCH_PLANS, "2026-09-26");

    expect(shortForm).toEqual(fullForm);
    expect(shortForm).toEqual([1, 2, 3]);
  });

  it("«2026-09» берёт месяц: все дни сентября и ничего из октября", () => {
    expect(matchingIds(SEARCH_PLANS, "2026-09")).toEqual([1, 2, 3]);
  });

  it("ведущий ноль не мешает: «09» — тот же сентябрь", () => {
    expect(matchingIds(SEARCH_PLANS, "09")).toEqual([1, 2, 3]);
  });

  it("одиночная цифра «2» — второй план за любую дату", () => {
    expect(matchingIds(SEARCH_PLANS, "2")).toEqual([2, 5]);
  });

  it("части запроса соединяются по И, а не по ИЛИ", () => {
    // 26.09 подходит под «26», но не под «10» — 26.10 подходит под оба.
    expect(matchingIds(SEARCH_PLANS, "26 10")).toEqual([6]);
  });

  it("нецифровые куски отбрасываются, цифровые работают", () => {
    expect(matchingIds(SEARCH_PLANS, "26 план")).toEqual([1, 2, 3, 6]);
  });

  it("запрос без чисел ничего не находит: искать больше нечем", () => {
    expect(matchingIds(SEARCH_PLANS, "план")).toEqual([]);
  });

  it("пустая строка и строка из одних разделителей — выборка не меняется", () => {
    const all = [1, 2, 3, 4, 5, 6];
    expect(matchingIds(SEARCH_PLANS, "")).toEqual(all);
    expect(matchingIds(SEARCH_PLANS, " . / - ")).toEqual(all);
  });

  it("«0» не находит ни дня, ни месяца, ни номера", () => {
    expect(matchingIds(SEARCH_PLANS, "0")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// buildPlanList — потолок видимых
// ---------------------------------------------------------------------------

describe("buildPlanList: потолок", () => {
  it("без поиска показывает 8 карточек, с поиском — 20", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(25)));

    const plain = buildPlanList(entries, "", 0);
    expect(plain.visible).toHaveLength(8);
    expect(plain.hiddenCount).toBe(17);

    const searched = buildPlanList(entries, "09", 0);
    expect(searched.visible).toHaveLength(20);
    expect(searched.hiddenCount).toBe(5);
  });

  it("extraVisible доклеивает по шагу 20 и снимает кнопку", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(25)));

    const once = buildPlanList(entries, "09", 20);
    expect(once.visible).toHaveLength(25);
    expect(once.hiddenCount).toBe(0);
  });

  it("когда всё помещается, скрытых нет", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(3)));
    const list = buildPlanList(entries, "", 0);

    expect(list.visible).toHaveLength(3);
    expect(list.hiddenCount).toBe(0);
  });

  it("строка из одних разделителей — это отсутствие запроса: потолок 8", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(25)));
    const list = buildPlanList(entries, " . / - ", 0);

    expect(list.visible).toHaveLength(8);
    expect(list.hiddenCount).toBe(17);
  });

  it("запрос без чисел даёт пустую выборку, а не полный список", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(25)));
    const list = buildPlanList(entries, "абв", 0);

    expect(list.visible).toEqual([]);
    expect(list.hiddenCount).toBe(0);
  });

  it("цифра среди мусора включает потолок 20", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(25)));
    const list = buildPlanList(entries, "09 хвост", 0);

    expect(list.visible).toHaveLength(20);
    expect(list.hiddenCount).toBe(5);
  });

  it("выбор порядка не меняет: список — это совпадения по датам", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(12)));

    // Ни выбранного id, ни набора выбранных функция не принимает — выбор
    // живёт в полосе ярлыков, а не в порядке карточек.
    expect(planIds(buildPlanList(entries, "", 0).visible)).toEqual([
      12, 11, 10, 9, 8, 7, 6, 5,
    ]);
  });

  it("выбранный план за потолком остаётся в списке скрытым, а не поднимается наверх", () => {
    const entries = buildPlanEntries(backendOrder(planSeries(12)));
    const oldest = entries[entries.length - 1];
    expect(oldest.number).toBe(1);

    const list = buildPlanList(entries, "", 0);

    expect(planIds(list.visible)).not.toContain(oldest.plan.id);
    expect(list.hiddenCount).toBe(4);
  });
});

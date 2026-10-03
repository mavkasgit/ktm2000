import type { DailyPlanSummary } from "@/shared/api/shopfloor";

/**
 * Список дневных планов в панели участка.
 *
 * Бэкенд отдаёт все планы участка плоским списком без пагинации
 * (`GET /daily-plans/sections/{id}`, сортировка `plan_date DESC,
 * created_at DESC`), поэтому ограничение и поиск живут здесь, на
 * клиенте: данные уже загружены, второй запрос ничего бы не купил.
 *
 * Порядок списка — всегда по дате, **независимо от выбора**: выбранный
 * план помечается на месте, а его ярлык живёт в полосе «Выбрано» над
 * списком. Раньше выбранное всплывало в отдельный блок наверху, и
 * карточка перескакивала через пол-панели на каждый клик — следить за
 * списком было нельзя. Ярлыки выбранных показываются целиком, поэтому
 * выбранный план не может пропасть из панели ни из-за поиска, ни из-за
 * потолка карточек.
 */

/**
 * Карточек без поисковой строки. Число выведено из высоты: панель тянется
 * на 80% колонки, и восемь карточек помещаются в неё целиком — вместе с
 * заголовком, строкой поиска и самой кнопкой «Показать ещё». Девять ужмется
 * или полезет внутрь прокрутки, то есть потолок перестанет быть честным.
 */
export const DEFAULT_PLAN_LIMIT = 8;
/** С поиском показываем больше — иначе строка фильтра почти бесполезна. */
export const SEARCH_PLAN_LIMIT = 20;
/** Шаг кнопки «Показать ещё». Числа в подписи нет намеренно. */
export const PLAN_SHOW_MORE_STEP = 20;

export type DailyPlanListEntry = {
  plan: DailyPlanSummary;
  /** Номер плана среди планов той же даты, в порядке создания. */
  number: number;
};

export type DailyPlanList = {
  /** Совпадения с поиском в порядке дат, обрезанные потолком. */
  visible: DailyPlanListEntry[];
  /** Сколько совпадений скрыто под кнопкой «Показать ещё». */
  hiddenCount: number;
};

/**
 * Разбирает поисковый запрос на числовые части по `.`, `-`, `/` и
 * пробелу. Нецифровые куски отбрасываются: искать больше нечем,
 * а выдумывать несуществующие поля поиска нельзя.
 *
 * `null` — запроса нет (пустая строка или одни разделители): показываем
 * обычный список. Пустой массив — запрос есть, но числовых частей в
 * нём нет: это запрос, который не может ничего найти.
 */
function parseQueryParts(query: string): number[] | null {
  const parts = query
    .split(/[\s./-]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  if (parts.length === 0) return null;
  return parts.filter((part) => /^\d+$/.test(part)).map((part) => Number(part));
}

/**
 * Номер плана среди планов той же даты в порядке создания.
 *
 * Считается по полному списку до среза: при отсечении десяти последних
 * «План №2» иначе превратился бы в «№1».
 */
export function buildPlanEntries(plans: DailyPlanSummary[]): DailyPlanListEntry[] {
  const numbersById = new Map<number, number>();
  const countersByDate = new Map<string, number>();
  const ordered = [...plans].sort((left, right) => {
    if (left.plan_date !== right.plan_date) return left.plan_date < right.plan_date ? 1 : -1;
    return left.created_at.localeCompare(right.created_at);
  });
  for (const plan of ordered) {
    const next = (countersByDate.get(plan.plan_date) ?? 0) + 1;
    countersByDate.set(plan.plan_date, next);
    numbersById.set(plan.id, next);
  }
  return plans.map((plan) => ({ plan, number: numbersById.get(plan.id) ?? 1 }));
}

/**
 * Совпадение плана с запросом: каждая числовая часть запроса должна
 * совпасть с днём, месяцем, годом или номером плана. Части сравниваются
 * численно, поэтому `26` находит 26-е число, `26.09` и `2026-09-26` —
 * конкретный день, `2026-09` — сентябрь, `2` — второй план за любую
 * дату.
 */
export function planMatchesQuery(entry: DailyPlanListEntry, query: string): boolean {
  const parts = parseQueryParts(query);
  if (parts === null) return true;
  if (parts.length === 0) return false;
  const [year, month, day] = entry.plan.plan_date.split("-").map(Number);
  return parts.every((part) => part === year || part === month || part === day || part === entry.number);
}

/**
 * Совпадения с поиском в порядке дат, обрезанные потолком видимых
 * карточек. Выбор здесь не участвует: он ничего не переставляет, а
 * выбранные планы показывает полоса ярлыков.
 */
export function buildPlanList(
  entries: DailyPlanListEntry[],
  query: string,
  extraVisible: number,
): DailyPlanList {
  const hasQuery = parseQueryParts(query) !== null;
  const matching = entries.filter((entry) => planMatchesQuery(entry, query));
  const limit = (hasQuery ? SEARCH_PLAN_LIMIT : DEFAULT_PLAN_LIMIT) + extraVisible;
  const visible = matching.slice(0, limit);
  return { visible, hiddenCount: matching.length - visible.length };
}

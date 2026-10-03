import type { DailyPlanSummary } from "@/shared/api/shopfloor";

/**
 * Список дневных планов в панели участка.
 *
 * Бэкенд отдаёт все планы участка плоским списком без пагинации
 * (`GET /daily-plans/sections/{id}`, сортировка `plan_date DESC,
 * created_at DESC`), поэтому ограничение и поиск живут здесь, на
 * клиенте: данные уже загружены, второй запрос ничего бы не купил.
 *
 * Порядок вывода — три блока:
 *   1. «Выбрано (N)» — выбранные планы, подходящие под поиск;
 *   2. обычные совпадения, по дате;
 *   3. «Не найдено среди выбранных (N)» — выбранные, которые поиск
 *      отсеял. Без этого блока выбранный план исчезал бы из панели
 *      при любом запросе, хотя доска продолжала показывать его
 *      задания.
 *
 * Потолок видимых карточек считается по сумме блоков 1 и 2: третий
 * блок показывается целиком, иначе скрытый выбранный план снова
 * стал бы невидимым.
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

export type DailyPlanListBlocks = {
  selected: DailyPlanListEntry[];
  others: DailyPlanListEntry[];
  selectedOutOfSearch: DailyPlanListEntry[];
  /** Сколько карточек скрыто под кнопкой «Показать ещё». */
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
 * Раскладывает планы по блокам панели с учётом выбора и потолка
 * видимых карточек.
 */
export function buildPlanListBlocks(
  entries: DailyPlanListEntry[],
  selectedPlanIds: Set<number>,
  query: string,
  extraVisible: number,
): DailyPlanListBlocks {
  const hasQuery = parseQueryParts(query) !== null;
  const selected: DailyPlanListEntry[] = [];
  const others: DailyPlanListEntry[] = [];
  const selectedOutOfSearch: DailyPlanListEntry[] = [];
  for (const entry of entries) {
    const isSelected = selectedPlanIds.has(entry.plan.id);
    const matches = planMatchesQuery(entry, query);
    if (isSelected && matches) {
      selected.push(entry);
    } else if (!isSelected && matches) {
      others.push(entry);
    } else if (isSelected) {
      selectedOutOfSearch.push(entry);
    }
  }

  const limit = (hasQuery ? SEARCH_PLAN_LIMIT : DEFAULT_PLAN_LIMIT) + extraVisible;
  const visibleSelected = selected.slice(0, limit);
  const visibleOthers = others.slice(0, Math.max(0, limit - visibleSelected.length));
  const hiddenCount = selected.length + others.length - visibleSelected.length - visibleOthers.length;

  return {
    selected: visibleSelected,
    others: visibleOthers,
    selectedOutOfSearch,
    hiddenCount,
  };
}

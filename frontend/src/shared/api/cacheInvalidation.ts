/**
 * Реестр сброса кэша: единственное место, где описано, какие query-ключи
 * принадлежат домену данных и какое действие какой домен затрагивает.
 *
 * ## Почему реестр, а не `invalidateQueries` в каждом экране
 *
 * Разбросанные вызовы уже разошлись: одиночное утверждение позиции сбрасывало
 * ключ строк контроля (`PlanPage.tsx`), массовое утверждение — нет (там был
 * только `plan.allPositions()`), импорт — тоже нет. Разница обнаруживалась
 * только вручную, симптом был «строка видна лишь после F5». Общий `staleTime`
 * в 5 минут превращал любую забытую инвалидацию в тихий баг вместо явного.
 *
 * ## Правило
 *
 * Экран НЕ пишет `invalidateQueries`. Он вызывает `invalidateAfter` с
 * бизнес-действием; какие домены задеты — решение матрицы `CACHE_ACTIONS`, а не
 * догадка автора вызова. Матрица покрыта unit-тестом.
 *
 * Событие с сервера (фаза 2, тикет #206) обязано звать тот же
 * `invalidateDomains`: второй способ сбросить кэш — это возврат бага.
 *
 * ## Почему префиксы написаны сырыми массивами
 *
 * Фабрика `queryKeys` подставляет в ключ параметры (`params ?? {}`, `spgId`,
 * `key ?? null`). Префикс, собранный самой фабрикой, поэтому НЕ совпадает с
 * реальным ключом, если параметр не совпадает по типу: `partialMatchKey` даёт
 * `typeof null !== typeof string → false`. Так были сломаны три инвалидации:
 * `transfers.readyAll()` и `transfers.historyAll()` подставляли `"all"` вместо
 * `spgId`, а `plan.duplicates()` — `null` вместо ключа планов. Здесь указаны
 * корни ключей, поэтому параметризованные варианты входят все.
 */
import type { QueryClient } from "@tanstack/react-query";

/** Домен данных ⇒ query-ключи, которые ему принадлежат. */
const CACHE_DOMAIN_KEYS = {
  /** План: файлы импорта, позиции, превью, дубликаты. */
  plan: [
    ["all-plan-files"],
    ["all-plan-positions"],
    ["plan-duplicates-all"],
    ["plan-preview"],
    ["plan-preview-page"],
    ["plan-position-detail"],
    ["batch-preview"],
    ["batch-force-delete-preview"],
  ],
  /** Контроль выполнения: строки плана в работе и карточка позиции. */
  execution: [["production-planning-rows"], ["production-planning-row-detail"], ["plans"]],
  /** Участки: доски задач, статистика, сводка, входящие передачи, дневные планы. */
  shopfloor: [
    ["shopfloor-board"],
    ["shopfloor-stats"],
    ["shopfloor-sections-summary"],
    ["shopfloor-incoming-transfers"],
    ["shopfloor-daily-plans"],
  ],
  /** Передачи между участками: готовое к передаче и журнал. */
  transfers: [["transfers-ready"], ["transfers-history"]],
  /** ГХП: снимки и дефекты. */
  spg: [["spg"], ["spgs"], ["spg-snapshot"], ["spg-defects"]],
  /** Склад: остатки и транзакции. */
  stock: [
    ["stock-balances"],
    ["stock-transactions"],
    ["stock-product-balance"],
    ["stock-remainder-import-operations"],
  ],
  /** Справочник участков: секции, операции, группы операций, маршруты. */
  sections: [["sections"], ["operations"], ["operation-groups"], ["routes"]],
  /** Справочник артикулов и сырья. */
  products: [["products"], ["raw-materials"]],
  /** Размерности артикула. */
  dimensions: [["product-dimensions"], ["dimension-types"]],
  /** Шаблоны импорта. */
  importTemplates: [["import-templates"]],
  /** Журнал действий. */
  audit: [["auditLogs"]],
  /** Отмена действий: журнал и деревья цепочек (корень `actions` покрывает и то и другое). */
  actions: [["actions"]],
  /** Сотрудники HRMS: список после синхронизации. */
  employees: [["employees"]],
  /** Резервные копии: список, конфигурация, задания, превью, текущее состояние. */
  backups: [["backups"], ["backup-config"], ["backup-jobs"], ["backup-previews"], ["current-preview"]],
} as const satisfies Record<string, readonly (readonly string[])[]>;

export type CacheDomain = keyof typeof CACHE_DOMAIN_KEYS;

/**
 * Матрица «бизнес-действие ⇒ задетые домены».
 *
 * Список доменов берётся с запасом: лишний сброс стоит одного лишнего запроса,
 * а недостаточный — это баг, который видит только пользователь и только через
 * F5. Если сомневаешься, добавляй домен, а не исключай.
 */
export const CACHE_ACTIONS = {
  /** Позиция плана утверждена — и одиночно, и массово: эффект одинаковый. */
  positionApproved: ["plan", "execution"],
  /** Позиция удалена из плана. */
  positionRemoved: ["plan", "execution"],
  /** Количество позиции изменено: пересчитываются задачи, остатки, передачи. */
  positionQuantityChanged: ["plan", "execution", "shopfloor", "transfers", "spg", "sections"],
  /** Позиции назначен маршрут. */
  routeAssigned: ["plan", "execution", "sections"],
  /** Импорт плана применён: появились позиции, задачи и списания. */
  importApplied: ["plan", "execution", "shopfloor", "spg", "sections", "products"],
  /** Импорт откатан или отброшен. */
  importDiscarded: ["plan", "execution"],
  /** Импорт удалён принудительно: снесены позиции, задания, передачи и проводки. */
  importForceDeleted: ["plan", "execution", "shopfloor", "transfers", "stock", "spg", "sections", "audit", "actions"],
  /** Позиция запущена, отменена, восстановлена, пройдена вручную, удалена из работы. */
  executionChanged: ["execution", "plan", "shopfloor", "transfers", "spg", "sections"],
  /** Задача на участке создана, завершена или скорректирована. */
  sectionTaskChanged: ["shopfloor", "transfers", "stock", "execution", "audit"],
  /** Дневной план участка создан, изменён или отозван. */
  dailyPlanChanged: ["shopfloor", "stock", "execution"],
  /** Материал передан или финально выпущен. */
  transferChanged: ["transfers", "shopfloor", "stock", "execution", "spg", "sections"],
  /** Остатки или транзакции изменились: корректировка, импорт остатков. */
  stockChanged: ["stock", "execution", "shopfloor", "spg", "transfers"],
  /** Изменён справочник артикулов, сырья или их размерностей. */
  productsChanged: ["products", "dimensions", "plan", "execution", "stock"],
  /** Изменены секции, операции или маршруты. */
  sectionsChanged: ["sections", "shopfloor", "transfers", "spg", "plan", "execution"],
  /** Изменён шаблон импорта. */
  importTemplatesChanged: ["importTemplates"],
  /** Действие отменено или исправлено. */
  actionReversed: ["actions", "audit", "execution", "shopfloor", "transfers", "stock"],
  /** Синхронизирован список сотрудников HRMS. */
  employeesSynced: ["employees"],
  /** Изменился бэкап или его конфигурация: список, превью, задания, текущее состояние. */
  backupsChanged: ["backups"],
} as const satisfies Record<string, readonly CacheDomain[]>;

/** Бизнес-действие, после которого нужно сбросить кэш. */
export type CacheAction = keyof typeof CACHE_ACTIONS;

/**
 * Сбросить домены. Единственная точка, которой пользуются и действия
 * пользователя, и (в будущем) события с сервера.
 */
export function invalidateDomains(queryClient: QueryClient, domains: readonly CacheDomain[]): Promise<void> {
  const invalidated = domains.flatMap((domain) =>
    CACHE_DOMAIN_KEYS[domain].map((queryKey) => queryClient.invalidateQueries({ queryKey: [...queryKey] })),
  );

  // Добивающий refetch для записей, которые ещё НИКОГДА не получили данных.
  //
  // Найдено на живом E2E (`full-cycle`): запись строк «Контроля выполнения»,
  // созданная debounce'ом поиска, к моменту инвалидации ещё не отдала ни
  // одного результата. Её первый GET уходит ДО коммита мутации, поэтому
  // сервер честно отвечает прежним состоянием, а `invalidateQueries` для
  // записи без данных последующего refetch не заводит. Устаревший ответ
  // закрепляется в кэше навсегда: экран остаётся на «Утверждён» после
  // запуска позиции в работу, пока не случится F5.
  //
  // Именно `state.data === undefined`, а не `dataUpdateCount === 0`:
  // счётчик — свойство истории обновлений, а «данных ещё нет» — это
  // состояние query. И важно, что выборка узкая: записи с данными (и тем
  // более активные) ведут себя как раньше, а неактивные записи других
  // доменов не превращаются в prefetch (`refetchType: "all"` был бы
  // расширением контракта механизма ради одного случая).
  const awaitingFirstData = domains
    .flatMap((domain) => CACHE_DOMAIN_KEYS[domain].map((queryKey) => [...queryKey] as const))
    .flatMap((queryKey) => queryClient.getQueryCache().findAll({ queryKey: [...queryKey] }))
    .filter((query) => query.state.data === undefined);

  // Дождаться текущего (уже ушедшего до коммита) ответа и только после него
  // перезапросить: `refetchQueries` для записи В ПОЛЁТЕ молча пропускает её.
  // Поэтому «сначала дождаться, потом refetch» — единственный порядок, при
  // котором свежий запрос действительно уходит.
  const refetchAfterInFlight = awaitingFirstData.map(async (query) => {
    await query.promise?.catch(() => undefined);
    await queryClient.refetchQueries({ queryKey: query.queryKey });
  });

  return Promise.all([...invalidated, ...refetchAfterInFlight]).then(() => undefined);
}

/**
 * Сбросить вообще всё — для действий, которые меняют саму БД (восстановление
 * из бэкапа), а не домен данных. Перечислить задетые ключи здесь нельзя:
 * после восстановления невалиден любой запрос, включая тот, чьего ключа ещё
 * нет в `CACHE_DOMAIN_KEYS`. Поэтому «сбросить всё» живёт здесь же, в
 * реестре, а не размазывается по хукам прямыми вызовами (ADR-0041).
 */
export function invalidateEverything(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries().then(() => undefined);
}

/** Сбросить домены по бизнес-действию. Основной вход для экранов. */
export function invalidateAfter(queryClient: QueryClient, action: CacheAction): Promise<void> {
  return invalidateDomains(queryClient, CACHE_ACTIONS[action]);
}

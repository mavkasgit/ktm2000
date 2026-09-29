import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { CACHE_ACTIONS, invalidateAfter, invalidateDomains, invalidateEverything } from "./cacheInvalidation";
import { queryKeys } from "./queryKeys";

/**
 * Реестр сброса кэша.
 *
 * Ключи берутся из настоящей фабрики `queryKeys`, а не из литералов: смысл теста
 * в том, что префикс реестра совпадает с ключом, которым реально пользуется
 * экран. Именно на этом расходились инвалидации передач и дубликатов плана.
 */
function clientWithKeys(keys: readonly (readonly unknown[])[]) {
  const queryClient = new QueryClient();
  for (const queryKey of keys) {
    queryClient.setQueryData([...queryKey], {});
  }
  return queryClient;
}

const invalidated = (queryClient: QueryClient, queryKey: readonly unknown[]) =>
  queryClient.getQueryState([...queryKey])?.isInvalidated === true;

/**
 * Дождаться данных в query. Резолв промиса проходит через несколько
 * микротасков, поэтому одного `await Promise.resolve()` мало: ждём по
 * состоянию, а не по числу тиков.
 */
async function untilData(queryClient: QueryClient, queryKey: readonly unknown[], expected: string) {
  for (let i = 0; i < 100; i++) {
    if (queryClient.getQueryData(queryKey) === expected) return;
    await Promise.resolve();
  }
  throw new Error(
    `query так и не получил ${expected}: ${JSON.stringify(queryClient.getQueryData(queryKey))}`,
  );
}

/**
 * Ответ, который отдаёт тест, когда он сам решит. `Promise.withResolvers`
 * требует `lib: es2024`, а проект собран под ES2020, поэтому гейт локальный.
 */
type TestGate<T> = { promise: Promise<T>; resolve: (value: T) => void };

function testGate<T>(): TestGate<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("реестр сброса кэша", () => {
  it("утверждение позиции сбрасывает и план, и контроль выполнения", async () => {
    // Ключи экранов: сводная таблица плана и строки «Контроля выполнения»
    // с параметрами сортировки/страницы — как их строят страницы.
    const planRows = queryKeys.plan.allPositions({ limit: 50, offset: 0 });
    const execRows = queryKeys.execution.rows({ limit: 50, offset: 0, sort: "id:asc" });
    const queryClient = clientWithKeys([planRows, execRows]);

    await invalidateAfter(queryClient, "positionApproved");

    expect(invalidated(queryClient, planRows)).toBe(true);
    expect(invalidated(queryClient, execRows)).toBe(true);
  });

  it("передача сбрасывает готовое к передаче и журнал при любом spgId", async () => {
    // Регрессия: `transfers.readyAll()` подставлял "all" вместо spgId, из-за
    // чего не совпадал ни один реальный ключ — передачи не обновлялись нигде.
    const readyNull = queryKeys.transfers.ready(null, { limit: 50, offset: 0 });
    const readySpg = queryKeys.transfers.ready(7, { limit: 50, offset: 0 });
    const historySpg = queryKeys.transfers.history(7, { limit: 50, offset: 0 });
    const queryClient = clientWithKeys([readyNull, readySpg, historySpg]);

    await invalidateAfter(queryClient, "transferChanged");

    expect(invalidated(queryClient, readyNull)).toBe(true);
    expect(invalidated(queryClient, readySpg)).toBe(true);
    expect(invalidated(queryClient, historySpg)).toBe(true);
  });

  it("дубликаты плана сбрасываются при ключе со списком планов", async () => {
    // Регрессия: `plan.duplicates()` подставлял `null`, а страница пишет
    // `plan.duplicates(planIds.join(","))` — ключи не совпадали по типу.
    const duplicates = queryKeys.plan.duplicates("12,13");
    const queryClient = clientWithKeys([duplicates]);

    await invalidateAfter(queryClient, "positionApproved");

    expect(invalidated(queryClient, duplicates)).toBe(true);
  });

  it("не трогает то, что действие не задевает", async () => {
    // Страховка от «сбросить вообще всё»: инвалидация лишнего домена стоит
    // лишнего запроса на каждом экране.
    const backups = queryKeys.backups.all();
    const products = queryKeys.products.all();
    const queryClient = clientWithKeys([backups, products]);

    await invalidateAfter(queryClient, "positionApproved");

    expect(invalidated(queryClient, products)).toBe(false);
    expect(invalidated(queryClient, backups)).toBe(false);
  });

  it("задача участка сбрасывает доску, передачи и остатки", async () => {
    const board = queryKeys.shopfloor.board(4, { limit: 50, offset: 0 });
    const ready = queryKeys.transfers.ready(null, {});
    const balances = queryKeys.stock.balances({ limit: 50, offset: 0 });
    const execRows = queryKeys.execution.rows({ limit: 50, offset: 0 });
    const queryClient = clientWithKeys([board, ready, balances, execRows]);

    await invalidateAfter(queryClient, "sectionTaskChanged");

    const DOMAINS: Record<string, true> = {
      plan: true,
      execution: true,
      shopfloor: true,
      transfers: true,
      spg: true,
      stock: true,
      sections: true,
      products: true,
      dimensions: true,
      importTemplates: true,
      audit: true,
      actions: true,
      employees: true,
      backups: true,
    };
    for (const [action, actionDomains] of Object.entries(CACHE_ACTIONS)) {
      expect(actionDomains.length, `у действия ${action} пустой список доменов`).toBeGreaterThan(0);
      for (const domain of actionDomains) {
        expect(
          DOMAINS[domain],
          `действие ${action} ссылается на неизвестный домен ${domain}`,
        ).toBe(true);
      }
    }
  });

  it("синхронизация сотрудников сбрасывает список при любых параметрах", async () => {
    // Регрессия: у `EmployeesPage` не было домена в реестре, и он сбрасывал
    // ключ литералом `["employees"]` — мимо фабрики, а значит мимо любой
    // её будущей правки.
    const list = queryKeys.employees.list({ limit: 50, offset: 0, search: "Иванов" });
    const queryClient = clientWithKeys([list]);

    await invalidateAfter(queryClient, "employeesSynced");

    expect(invalidated(queryClient, list)).toBe(true);
  });

  it("изменение бэкапа сбрасывает список, конфигурацию и превью", async () => {
    // Регрессия: `useBackups` перечислял 15 ключей вручную и не покрывал
    // ключ, добавленный в `queryKeys.backups` позже.
    const list = queryKeys.backups.list({ limit: 50, offset: 0, sort: "created_at:desc" });
    const config = queryKeys.backups.config();
    const previews = queryKeys.backups.previews(3);
    const jobs = queryKeys.backups.jobs();
    const queryClient = clientWithKeys([list, config, previews, jobs]);

    await invalidateAfter(queryClient, "backupsChanged");

    expect(invalidated(queryClient, list)).toBe(true);
    expect(invalidated(queryClient, config)).toBe(true);
    expect(invalidated(queryClient, previews)).toBe(true);
    expect(invalidated(queryClient, jobs)).toBe(true);
  });

  it("применение импорта сбрасывает превью батча", async () => {
    // Регрессия: `planImportCaches` сбрасывал `batchPreview` точечно, мимо
    // реестра. Ключ параметризован batchId, но корень `batch-preview` в
    // домене `plan` покрывает все параметризованные варианты.
    const batch = [...queryKeys.plan.batchPreview(17), "light"];
    const planPreview = queryKeys.plan.preview(4);
    const queryClient = clientWithKeys([batch, planPreview]);

    await invalidateAfter(queryClient, "importApplied");

    expect(invalidated(queryClient, batch)).toBe(true);
    expect(invalidated(queryClient, planPreview)).toBe(true);
  });

  it("invalidateEverything сбрасывает и то, чего в реестре нет", async () => {
    // Восстановление БД переписывает базу целиком: невалиден любой запрос.
    const orphan = ["auth-me"] as const;
    const queryClient = clientWithKeys([orphan, queryKeys.execution.rows({ limit: 50, offset: 0 })]);

    await expect(invalidateEverything(queryClient)).resolves.toBeUndefined();

    expect(invalidated(queryClient, orphan)).toBe(true);
    expect(invalidated(queryClient, queryKeys.execution.rows({ limit: 50, offset: 0 }))).toBe(true);
  });

  it("invalidateDomains переживает повторный вызов", async () => {
    // Фаза 2 будет звать это на каждое событие с сервера — в том числе когда
    // экран размонтирован и записи в кэше может уже не быть.
    const queryClient = clientWithKeys([queryKeys.execution.rows({ limit: 50, offset: 0 })]);
    await expect(invalidateDomains(queryClient, ["execution", "plan"])).resolves.toBeUndefined();
  });

  it("запись без данных после инвалидации добирает свежий ответ", async () => {
    // Регрессия (живой баг, `full-cycle` / `single-line-cycle`): запись строк,
    // созданная debounce'ом поиска, ещё не отдавала ни одного результата, когда
    // пришла инвалидация после take-to-work. Её первый GET уходил ДО коммита,
    // последующего refetch не было, и устаревший ответ навсегда оставался в
    // кэше — строка не перерисовывалась из «Утверждён» в «Запущен».
    // Условие боевого провала: наблюдатель есть, данных ещё нет.
    const queryClient = new QueryClient();
    const queryKey = queryKeys.execution.rows({ search: "ЮП-009", limit: 50, offset: 0 });
    const gates: TestGate<string>[] = [];
    const observer = new QueryObserver(queryClient, {
      queryKey,
      queryFn: () => {
        const g = testGate<string>();
        gates.push(g);
        return g.promise;
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    await Promise.resolve();
    expect(gates).toHaveLength(1);

    // Мутация завершилась, а первый ответ ещё в полёте. Промис инвалидации не
    // ждём: он завершится лишь с добивающим fetch, ради которого проверка и
    // написана, — иначе она ждала бы сама себя.
    void invalidateAfter(queryClient, "executionChanged");

    // Первый GET приходит и приносит состояние, прочитанное ДО коммита.
    gates[0].resolve("approved");
    await untilData(queryClient, queryKey, "approved");
    await Promise.resolve();

    // Добивающий refetch обязан был уйти после него: без него устаревший ответ
    // остался бы единственным содержимым кэша — ровно тот баг, что ловит E2E.
    expect(gates).toHaveLength(2);
    gates[1].resolve("released");
    await untilData(queryClient, queryKey, "released");
    unsubscribe();
  });

  it("запись, у которой данные уже есть, перечитывается ровно один раз", async () => {
    // Граница фикса: поведение записи с данными не меняется. Реестр не должен
    // превращаться в prefetch-механизм для всего кэша.
    const queryClient = new QueryClient();
    const queryKey = queryKeys.execution.rows({ limit: 50, offset: 0 });
    const gates: TestGate<string>[] = [];
    const observer = new QueryObserver(queryClient, {
      queryKey,
      queryFn: () => {
        const g = testGate<string>();
        gates.push(g);
        return g.promise;
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    await Promise.resolve();
    gates[0].resolve("approved");
    await untilData(queryClient, queryKey, "approved");

    void invalidateAfter(queryClient, "executionChanged");
    await Promise.resolve();
    await Promise.resolve();

    // Ровно одна перечитка — как до фикса, никакого второго запроса.
    expect(gates).toHaveLength(2);
    gates[1].resolve("released");
    await untilData(queryClient, queryKey, "released");
    unsubscribe();
  });

});

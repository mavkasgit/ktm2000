import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { CACHE_ACTIONS, invalidateAfter, invalidateDomains } from "./cacheInvalidation";
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

  it("invalidateDomains переживает повторный вызов", async () => {
    // Фаза 2 будет звать это на каждое событие с сервера — в том числе когда
    // экран размонтирован и записи в кэше может уже не быть.
    const queryClient = clientWithKeys([queryKeys.execution.rows({ limit: 50, offset: 0 })]);
    await expect(invalidateDomains(queryClient, ["execution", "plan"])).resolves.toBeUndefined();
  });
});

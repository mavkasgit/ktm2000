/**
 * Критерий приёмки #206: интервал опроса операционных экранов объявлен одной
 * константой в коридоре владельца 10–15 с, а фон не опрашивается.
 *
 * Это не проверка «значения по умолчанию ради значения»: коридор и запрет на
 * опрос фона — прямая формулировка решения (PLAN §5, ADR-0041), и без этой
 * пробы интервал можно поменять молча.
 */
import { describe, expect, it } from "vitest";

import { OPERATIONAL_POLL_INTERVAL_MS, operationalPollingOptions } from "./operationalPolling";

describe("опции опроса операционных экранов", () => {
  it("интервал лежит в разрешённом коридоре 10–15 с", () => {
    expect(OPERATIONAL_POLL_INTERVAL_MS).toBeGreaterThanOrEqual(10_000);
    expect(OPERATIONAL_POLL_INTERVAL_MS).toBeLessThanOrEqual(15_000);
  });

  it("query берёт интервал из константы и не опрашивает фон", () => {
    expect(operationalPollingOptions.refetchInterval).toBe(OPERATIONAL_POLL_INTERVAL_MS);
    expect(operationalPollingOptions.refetchIntervalInBackground).toBe(false);
  });
});

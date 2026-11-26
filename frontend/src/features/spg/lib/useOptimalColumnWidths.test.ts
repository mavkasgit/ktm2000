/**
 * Хук ширин предпросмотра (#483): кэш по листу, отсутствие пересчёта на
 * поиск/сортировку, пересчёт на ресайз, fallback без прыжка.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RemainderImportItem } from "@/shared/api/stock";

import type {
  PreviewRowMeasurement,
  PreviewWidthEngine,
} from "./previewTextMeasurer";
import {
  MIN_ROWS_FOR_MODEL,
  useOptimalColumnWidths,
} from "./useOptimalColumnWidths";

function makeItems(count: number): RemainderImportItem[] {
  return Array.from({ length: count }, (_, index) => ({
    source_row_number: index + 1,
    status: "valid",
    errors: [],
    warnings: [],
    completed_stages: [],
  })) as unknown as RemainderImportItem[];
}

const nameFont = {
  family: "Test Sans",
  sizePx: 11,
  weight: 400,
  lineHeightPx: 16.5,
};

interface EngineHandle {
  engine: PreviewWidthEngine;
  buildRowsCalls: () => number;
}

function makeEngine(): EngineHandle {
  let calls = 0;
  const engine: PreviewWidthEngine = {
    fonts: {
      name: nameFont,
      errors: { ...nameFont, weight: 500, lineHeightPx: 15.125 },
      pill: { ...nameFont, sizePx: 10 },
    },
    measurer: {
      prepare: (text) => ({ text }),
      naturalWidth: (prepared) => (prepared as { text: string }).text.length * 6,
      maxWordWidth: (prepared) => (prepared as { text: string }).text.length * 6,
      lineCount: () => 2,
    },
    buildRows(items): PreviewRowMeasurement[] {
      calls += 1;
      return items.map((item) => ({
        rowKey: item.source_row_number,
        nameText: "Наименование",
        errorsText: "Ошибка",
        errorsWraps: true,
        pillWidth: 120,
      }));
    },
  };
  return { engine, buildRowsCalls: () => calls };
}

const flush = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useOptimalColumnWidths", () => {
  it("без флага ничего не считает", async () => {
    const factory = vi.fn();
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: false,
        sheetIndex: 0,
        items: makeItems(30),
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("off");
    expect(result.current.result).toBeNull();
    expect(factory).not.toHaveBeenCalled();
  });

  it("считает ширины и высоты по первому ответу листа", async () => {
    const handle = makeEngine();
    const factory = async () => handle.engine;
    const items = makeItems(30);
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items,
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("ready");
    expect(result.current.sheetIndex).toBe(0);
    expect(result.current.result?.shares.errors).toMatch(/%$/);
    expect(result.current.result?.rowHeights.size).toBe(30);
  });

  it("не пересчитывает на новый массив строк того же листа (поиск/сортировка)", async () => {
    const handle = makeEngine();
    const factory = async () => handle.engine;
    const { result, rerender } = renderHook(
      ({ items }: { items: RemainderImportItem[] }) =>
        useOptimalColumnWidths({
          enabled: true,
          sheetIndex: 0,
          items,
          operations: null,
          containerWidth: 1500,
          engineFactory: factory,
        }),
      { initialProps: { items: makeItems(30) } },
    );
    await flush();
    const firstResult = result.current.result;
    expect(handle.buildRowsCalls()).toBe(1);

    // Фильтр/сортировка присылают новый массив — снапшот листа не меняется.
    rerender({ items: makeItems(12) });
    await flush();

    expect(handle.buildRowsCalls()).toBe(1);
    expect(result.current.result).toBe(firstResult);
  });

  it("пересчитывает на изменение ширины контейнера после дебаунса", async () => {
    const handle = makeEngine();
    const factory = async () => handle.engine;
    const { result, rerender } = renderHook(
      ({ width }: { width: number }) =>
        useOptimalColumnWidths({
          enabled: true,
          sheetIndex: 0,
          items: makeItems(30),
          operations: null,
          containerWidth: width,
          engineFactory: factory,
        }),
      { initialProps: { width: 1500 } },
    );
    await flush();
    expect(handle.buildRowsCalls()).toBe(1);

    rerender({ width: 1700 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(handle.buildRowsCalls()).toBe(2);
    expect(result.current.status).toBe("ready");
  });

  it("новый лист считается отдельно и не берёт ширины прошлого", async () => {
    const handle = makeEngine();
    const factory = async () => handle.engine;
    const { result, rerender } = renderHook(
      ({ sheet }: { sheet: number }) =>
        useOptimalColumnWidths({
          enabled: true,
          sheetIndex: sheet,
          items: makeItems(30),
          operations: null,
          containerWidth: 1500,
          engineFactory: factory,
        }),
      { initialProps: { sheet: 0 } },
    );
    await flush();
    const first = result.current.result;

    rerender({ sheet: 1 });
    // До готовности нового листа ширин нет — таблица показывается на долях.
    expect(result.current.result).toBeNull();
    await flush();
    expect(result.current.sheetIndex).toBe(1);
    expect(handle.buildRowsCalls()).toBe(2);
    expect(result.current.result).not.toBe(first);
  });

  it("ошибка движка — fallback на текущие доли", async () => {
    const factory = async () => {
      throw new Error("нет canvas");
    };
    const items = makeItems(30);
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items,
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("fallback");
    expect(result.current.result).toBeNull();
  });

  it("нет данных — pending, а не fallback: первый кадр не показывает доли", async () => {
    const factory = vi.fn();
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items: null,
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("pending");
    expect(result.current.result).toBeNull();
    expect(factory).not.toHaveBeenCalled();
  });

  it("пустой лист — fallback: таблица скажет «нет данных», спиннер не вечный", async () => {
    const factory = vi.fn();
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items: [],
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("fallback");
    expect(factory).not.toHaveBeenCalled();
  });

  it("мало строк — fallback без расчёта", async () => {
    const factory = vi.fn();
    const items = makeItems(MIN_ROWS_FOR_MODEL - 1);
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items,
        operations: null,
        containerWidth: 1500,
        engineFactory: factory,
      }),
    );
    await flush();
    expect(result.current.status).toBe("fallback");
    expect(factory).not.toHaveBeenCalled();
  });

  it("поздний результат после fallback не применяется — таблица не прыгает", async () => {
    let resolveEngine: ((engine: PreviewWidthEngine) => void) | null = null;
    const handle = makeEngine();
    const factory = () =>
      new Promise<PreviewWidthEngine>((resolve) => {
        resolveEngine = resolve;
      });
    const items = makeItems(30);
    const { result } = renderHook(() =>
      useOptimalColumnWidths({
        enabled: true,
        sheetIndex: 0,
        items,
        operations: null,
        containerWidth: 1500,
        fallbackAfterMs: 100,
        engineFactory: factory,
      }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(result.current.status).toBe("fallback");

    await act(async () => {
      resolveEngine?.(handle.engine);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe("fallback");
    expect(result.current.result).toBeNull();
  });
});

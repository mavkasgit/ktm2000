/**
 * Хук ширин колонок предпросмотра остатков (#483).
 *
 * Контракт из тикета:
 *
 * - **кэш по `sheet_index`** из первого полного нефильтрованного ответа:
 *   снапшот строк фиксируется при первом появлении листа, дальше поиск,
 *   сортировка и чипы на него не влияют;
 * - **пересчёт только на ширину контейнера** (дебаунс) — и один раз, когда
 *   догрузился справочник операций (от него зависят ширины пилюль);
 * - **никогда** на скролл/поиск/сортировку: всё это меняет `visibleItems`, а
 *   хук получает снапшот листа, а не отфильтрованный список;
 * - **без прыжка**: пока ширины не готовы, таблица не показывается (её держит
 *   скелетон запроса); если расчёт не уложился в `fallbackAfterMs` или упал,
 *   для листа фиксируется `fallback` — текущие доли — и поздний результат уже
 *   не применяется;
 * - **fallback**: мало данных (< `MIN_ROWS_FOR_MODEL`), пустой лист, ошибка
 *   движка — `result: null`, экран живёт на `remainderPreviewColumns`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { ImportOperationStep, RemainderImportItem } from "@/shared/api/stock";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import {
  computePreviewColumnWidths,
  type PreviewWidthResult,
} from "./previewColumnWidths";
import {
  createPreviewWidthEngine,
  type PreviewWidthEngine,
} from "./previewTextMeasurer";

/** Меньше строк — модель шумит: остаёмся на текущих долях. */
export const MIN_ROWS_FOR_MODEL = 20;
/** Пауза пересчёта на ресайз: дебаунс, а не расчёт на каждый кадр. */
export const RESIZE_DEBOUNCE_MS = 150;
/** Предел ожидания расчёта перед честным fallback. */
export const FALLBACK_AFTER_MS = 600;

export type OptimalColumnWidthsStatus = "off" | "pending" | "ready" | "fallback";

export interface UseOptimalColumnWidthsOptions {
  enabled: boolean;
  sheetIndex: number;
  /** Первый полный нефильтрованный ответ листа; `null` — данных ещё нет. */
  items: readonly RemainderImportItem[] | null;
  operations: readonly ImportOperationStep[] | null | undefined;
  /** Ширина контейнера таблицы, CSS px. */
  containerWidth: number;
  /** Тесты: подмена движка (в jsdom нет ни canvas, ни pretext). */
  engineFactory?: () => Promise<PreviewWidthEngine>;
  debounceMs?: number;
  fallbackAfterMs?: number;
}

export interface OptimalColumnWidthsState {
  status: OptimalColumnWidthsStatus;
  /** Ширины относятся только к этому листу: чужой результат не применяется. */
  sheetIndex: number | null;
  result: PreviewWidthResult | null;
}

const INITIAL_STATE: OptimalColumnWidthsState = {
  status: "off",
  sheetIndex: null,
  result: null,
};

/** Один движок на приложение: кэш подготовленного текста переживает ресайз. */
let sharedEngine: Promise<PreviewWidthEngine> | null = null;

function defaultEngineFactory(): Promise<PreviewWidthEngine> {
  sharedEngine ??= createPreviewWidthEngine().catch((error: unknown) => {
    sharedEngine = null;
    throw error;
  });
  return sharedEngine;
}

export function useOptimalColumnWidths(
  options: UseOptimalColumnWidthsOptions,
): OptimalColumnWidthsState {
  const {
    enabled,
    sheetIndex,
    items,
    operations,
    containerWidth,
    debounceMs = RESIZE_DEBOUNCE_MS,
    fallbackAfterMs = FALLBACK_AFTER_MS,
  } = options;

  const debouncedWidth = useDebouncedValue(
    Math.max(0, Math.round(containerWidth)),
    debounceMs,
  );

  // Снапшот первого непустого ответа листа: дальше поиск/сортировка/фильтры
  // присылают новые массивы, и пересчитывать по ним ширины нельзя.
  const [snapshot, setSnapshot] = useState<{
    sheet: number;
    items: readonly RemainderImportItem[];
  } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    setSnapshot((previous) => {
      if (previous?.sheet === sheetIndex) return previous;
      if (!items || items.length === 0) return null;
      return { sheet: sheetIndex, items };
    });
  }, [enabled, sheetIndex, items]);

  const snapshotItems = snapshot?.sheet === sheetIndex ? snapshot.items : null;

  const results = useRef(new Map<string, PreviewWidthResult>());
  const settled = useRef(new Map<string, "ready" | "fallback">());
  const [state, setState] = useState<OptimalColumnWidthsState>(() =>
    options.enabled
      ? { status: "pending", sheetIndex: null, result: null }
      : INITIAL_STATE,
  );

  /** Не перерисовывать, если статус не изменился: защита от новых ссылок. */
  const setStatus = useCallback(
    (
      status: OptimalColumnWidthsStatus,
      result: PreviewWidthResult | null = null,
    ) => {
      setState((previous) =>
        previous.status === status &&
        previous.sheetIndex === sheetIndex &&
        previous.result === result
          ? previous
          : { status, sheetIndex, result },
      );
    },
    [sheetIndex],
  );

  const operationsKey = operations?.length ? operations.length : 0;
  // Фабрика движка и справочник операций читаются из ref: их новая ссылка на
  // каждый рендер не должна перезапускать эффект (иначе расчёт зацикливается).
  const engineFactory = options.engineFactory ?? defaultEngineFactory;
  const engineFactoryRef = useRef(engineFactory);
  engineFactoryRef.current = engineFactory;
  const operationsRef = useRef(operations);
  operationsRef.current = operations;

  useEffect(() => {
    if (!enabled) {
      setState(INITIAL_STATE);
      return;
    }
    // Данных ещё нет — держим скелетон, но не называем это fallback: иначе
    // первый кадр после ответа успел бы показать текущие доли и прыгнуть.
    if (items === null || debouncedWidth <= 0) {
      setStatus("pending");
      return;
    }
    if (items.length === 0) {
      setStatus("fallback");
      return;
    }
    if (!snapshotItems) {
      // Снапшот фиксируется эффектом выше — один кадр, дальше расчёт.
      setStatus("pending");
      return;
    }
    if (snapshotItems.length < MIN_ROWS_FOR_MODEL) {
      setStatus("fallback");
      return;
    }

    const key = `${sheetIndex}|${debouncedWidth}|${operationsKey}`;
    const cached = results.current.get(key);
    if (cached) {
      setStatus("ready", cached);
      return;
    }
    if (settled.current.get(key) === "fallback") {
      setStatus("fallback");
      return;
    }

    let cancelled = false;
    setState((previous) => {
      if (previous.status === "pending" && previous.sheetIndex === sheetIndex) {
        return previous;
      }
      return previous.sheetIndex === sheetIndex && previous.result
        ? { ...previous, status: "pending" }
        : { status: "pending", sheetIndex, result: null };
    });

    const timer = window.setTimeout(() => {
      if (cancelled) return;
      settled.current.set(key, "fallback");
      setStatus("fallback");
    }, fallbackAfterMs);

    engineFactoryRef.current()
      .then((engine) => {
        if (cancelled) return;
        const rows = engine.buildRows(snapshotItems, operationsRef.current);
        const result = computePreviewColumnWidths({
          containerWidth: debouncedWidth,
          rows,
          measurer: engine.measurer,
          fonts: engine.fonts,
        });
        window.clearTimeout(timer);
        if (settled.current.get(key) === "fallback") return;
        results.current.set(key, result);
        settled.current.set(key, "ready");
        setState({ status: "ready", sheetIndex, result });
      })
      .catch(() => {
        if (cancelled) return;
        window.clearTimeout(timer);
        settled.current.set(key, "fallback");
        setStatus("fallback");
      });

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // `operations` участвует ключом (`operationsKey`), а не объектом: массив
    // пересоздаётся запросом, но его длина — единственное, что меняет расчёт.
  }, [
    enabled,
    sheetIndex,
    items,
    snapshotItems,
    operationsKey,
    debouncedWidth,
    fallbackAfterMs,
    setStatus,
  ]);

  if (!enabled) return INITIAL_STATE;
  if (state.sheetIndex !== null && state.sheetIndex !== sheetIndex) {
    return { status: "pending", sheetIndex, result: null };
  }
  return state;
}

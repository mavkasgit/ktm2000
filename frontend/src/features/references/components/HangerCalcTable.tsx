import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { toast } from "@/shared/ui/use-toast";
import { TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { DataTableColumnHeader } from "@/shared/ui/DataTableColumnHeader";
import { listProductsPaginated, listProductPairCatalog, patchProduct, getErrorMessage } from "@/shared/api/products";
import type { Product, ProductFilters, ProductPairCatalogEntry } from "@/shared/api/products";
import { calcHanger, calcPairedHanger } from "@/shared/api/hangerCalc";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import { effectiveRawLength, isHangerAutoMode, isSheetState, lengthKey, productLengths, sheetDims } from "@/shared/lib/hangerQuantity";
import {
  buildCalcItems,
  buildHangerCalcRows,
  buildPairedCalcItems,
  buildPairedHangerCalcRows,
  incompatibilityReason,
  resolvePairs,
  resultsToCalcMap,
  resultsToPairedCalcMap,
  rowSearchValues,
  sortHangerCalcRows,
  type CalcMap,
  type HangerCalcRow,
  type HangerCalcSortField,
  type PairedCalcMap,
  type PairedHangerCalcRow,
  type PairedPair,
} from "../lib/hangerCalcRows";
import {
  buildHangerCalcSortParam,
  hangerCalcCellValue,
  hangerCalcColumns,
} from "../lib/hangerCalcColumns";
import { HangerConstantsPanel } from "./HangerConstantsPanel";
import { HangerCalcRowView, type RowSaveState } from "./HangerCalcRowView";
import { PairedHangerRowView } from "./PairedHangerRowView";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { getAriaSort } from "@/shared/lib/multiSort";
import { cn } from "@/shared/utils/cn";

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

/** Таблица «Расчёт подвесов» (#64): все артикулы сырья, batch-расчёт, inline-правка. */
export function HangerCalcTable({
  readOnly,
  onEdit,
}: {
  readOnly: boolean;
  onEdit: (product: Product) => void;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [calcMap, setCalcMap] = useState<CalcMap>(new Map());
  const [productPairs, setProductPairs] = useState<ProductPairCatalogEntry[]>([]);
  const [pairedCalcMap, setPairedCalcMap] = useState<PairedCalcMap>(new Map());
  const [pairedIncompatible, setPairedIncompatible] = useState<Map<number, string>>(new Map());
  const [hanger, setHanger] = useState<HangerSettings | null>(null);
  const [incompatible, setIncompatible] = useState<Map<number, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rowStates, setRowStates] = useState<Record<number, RowSaveState | undefined>>({});
  const savedTimers = useRef<Map<number, number>>(new Map());
  // Актуальные продукты для пересчёта пар после inline-правки одиночного артикула.
  const productsRef = useRef<Product[]>([]);
  // Полный набор компонентов пар (#67): пары разрешаются даже при серверном
  // поиске (q), который фильтрует одиночные строки.
  const [pairProducts, setPairProducts] = useState<Product[]>([]);
  const pairProductsRef = useRef<Product[]>([]);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    handleSort,
    hasActiveFilters,
    resetAll,
  } = useFilterableTable<HangerCalcSortField>({
    // Поиск считается фильтром, а сортировка и фильтры колонок — общим
    // правилом хука: условие «активно» раньше было написано здесь руками и
    // могло разойтись с правилом на других экранах. Сортировка тоже живёт в
    // хуке: своё состояние рядом с ним делало счётчик слепым к сортировке.
    extraHasActive: search.trim().length > 0,
    onExtraReset: () => setSearch(""),
  });



  const setRowState = useCallback((id: number, state: RowSaveState | undefined) => {
    setRowStates((prev) => ({ ...prev, [id]: state }));
  }, []);

  // Серверный поиск и сортировка (ADR-0014): `q`/`sort` уходят на сервер,
  // чтобы поиск находил артикул за пределами лимита выгрузки (#84).
  const apiParams = useMemo(() => {
    const params: ProductFilters = {
      type: "component",
      limit: 2000,
    };
    // «Итог» и «Лимитер» считаются на клиенте, сервер их не сортирует.
    const sort = buildHangerCalcSortParam(sortConfigs);
    if (sort) params.sort = sort;
    return params;
  }, [sortConfigs]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Полный набор компонентов нужен для пар, когда серверный поиск (q)
      // сужает одиночные строки: парная строка A+B не должна пропадать (#67).
      const [list, pairCatalog, constants, allComponents] = await Promise.all([
        listProductsPaginated(apiParams),
        listProductPairCatalog(),
        calcHanger([]),
        apiParams.q
          ? listProductsPaginated({ type: "component", limit: 2000 })
          : Promise.resolve(null),
      ]);
      const pairProductsFull = allComponents?.items ?? list.items;

      const { items, refs, incompatible: incompatibles } = buildCalcItems(list.items, constants.hanger);
      let map: CalcMap = new Map();
      if (items.length > 0) {
        const resp = await calcHanger(items);
        map = resultsToCalcMap(refs, resp.results);
      }

      // Парные строки A+B (#150, источник — pairs-API): совместный расчёт по длинам пары.
      const pairs = resolvePairs(pairCatalog, pairProductsFull);
      const pairedItems = buildPairedCalcItems(pairs, constants.hanger);
      let pairedMap: PairedCalcMap = new Map();
      if (pairedItems.items.length > 0) {
        const resp = await calcPairedHanger(pairedItems.items);
        pairedMap = resultsToPairedCalcMap(pairedItems.refs, resp.results);
      }

      productsRef.current = list.items;
      pairProductsRef.current = pairProductsFull;
      setProducts(list.items);
      setPairProducts(pairProductsFull);
      setHanger(constants.hanger);
      setIncompatible(incompatibles);
      setCalcMap(map);
      setProductPairs(pairCatalog);
      setPairedCalcMap(pairedMap);
      setPairedIncompatible(pairedItems.incompatible);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [apiParams]);

  useEffect(() => {
    void load();
    const timers = savedTimers.current;
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
    };
  }, [load]);

  const recalcRow = useCallback(async (product: Product, settings: HangerSettings) => {
    const removeFromCalc = (prev: CalcMap): CalcMap => {
      if (!prev.has(product.id)) return prev;
      const next = new Map(prev);
      next.delete(product.id);
      return next;
    };
    const removeFromIncompatible = (prev: Map<number, string>): Map<number, string> => {
      if (!prev.has(product.id)) return prev;
      const next = new Map(prev);
      next.delete(product.id);
      return next;
    };

    if (isSheetState(product.dimension_state)) {
      // Лист (#126): пересчёт по осям полотна; ручной режим — без расчёта.
      if ((product.hanger_mode ?? "auto") !== "auto") {
        setCalcMap(removeFromCalc);
        setIncompatible(removeFromIncompatible);
        return;
      }
      const { lengthMm, widthMm, heightMm } = sheetDims(product);
      if (lengthMm == null) {
        setCalcMap(removeFromCalc);
        setIncompatible(removeFromIncompatible);
        return;
      }
      setIncompatible(removeFromIncompatible);
      const resp = await calcHanger([{
        kind: "sheet",
        perimeter_mm: null,
        mount_width_mm: null,
        length_mm: lengthMm,
        width_mm: widthMm,
        height_mm: product.dimension_state === "volume" ? heightMm : null,
      }]);
      const byLength = new Map<string, HangerCalcResult>();
      if (resp.results[0]) byLength.set(lengthKey(lengthMm), resp.results[0]);
      setCalcMap((prev) => {
        const next = new Map(prev);
        next.set(product.id, byLength);
        return next;
      });
      return;
    }

    if ((product.hanger_mode ?? "auto") !== "auto" || !isHangerAutoMode(product)) {
      setCalcMap(removeFromCalc);
      setIncompatible(removeFromIncompatible);
      return;
    }
    const reason = incompatibilityReason(product.mount_width_mm, settings);
    if (reason) {
      setIncompatible((prev) => {
        const next = new Map(prev);
        next.set(product.id, reason);
        return next;
      });
      setCalcMap(removeFromCalc);
      return;
    }
    setIncompatible(removeFromIncompatible);
    const lengths = productLengths(product);
    if (lengths.length === 0) {
      setCalcMap(removeFromCalc);
      return;
    }
    const records = product.lengths ?? [];
    const resp = await calcHanger(
      records.map((length) => ({
        perimeter_mm: product.perimeter_mm,
        mount_width_mm: product.mount_width_mm,
        length_mm: effectiveRawLength(length),
      })),
    );
    const byLength = new Map<string, HangerCalcResult>();
    resp.results.forEach((result, index) => {
      const normal = records[index]?.length_mm;
      if (normal != null) byLength.set(lengthKey(normal), result);
    });
    setCalcMap((prev) => {
      const next = new Map(prev);
      next.set(product.id, byLength);
      return next;
    });
  }, []);

  const recalcPairs = useCallback(async (pairList: PairedPair[], settings: HangerSettings) => {
    const items = buildPairedCalcItems(pairList, settings);
    let map: PairedCalcMap = new Map();
    if (items.items.length > 0) {
      const resp = await calcPairedHanger(items.items);
      map = resultsToPairedCalcMap(items.refs, resp.results);
    }
    setPairedIncompatible(items.incompatible);
    setPairedCalcMap(map);
  }, []);

  const commitField = useCallback(
    async (product: Product, field: "perimeter_mm" | "mount_width_mm", value: number | null) => {
      setRowState(product.id, { status: "saving" });
      try {
        const { data } = await patchProduct(product.id, { [field]: value });
        const nextProducts = productsRef.current.map((p) => (p.id === data.id ? data : p));
        productsRef.current = nextProducts;
        setProducts(nextProducts);
        const nextPairProducts = pairProductsRef.current.map((p) => (p.id === data.id ? data : p));
        pairProductsRef.current = nextPairProducts;
        setPairProducts(nextPairProducts);
        const settings = hanger;
        if (settings) {
          await recalcRow(data, settings);
          // Правка артикула влияет на парные строки, где он участвует (#67).
          await recalcPairs(resolvePairs(productPairs, nextPairProducts), settings);
        }
        setRowState(product.id, { status: "saved" });
        const previous = savedTimers.current.get(product.id);
        if (previous) window.clearTimeout(previous);
        savedTimers.current.set(
          product.id,
          window.setTimeout(() => {
            setRowStates((prev) =>
              prev[product.id]?.status === "saved" ? { ...prev, [product.id]: undefined } : prev,
            );
          }, 2000),
        );
      } catch (e) {
        const message = getErrorMessage(e);
        // 422 при inline-правке габарита → помечаем строку как несовместимую,
        // чтобы пользователь видел красную строку с причиной, а не только тост (#64).
        if (hanger && field === "mount_width_mm" && value != null) {
          const reason = incompatibilityReason(value, hanger);
          if (reason) {
            setIncompatible((prev) => {
              const next = new Map(prev);
              next.set(product.id, reason);
              return next;
            });
            setCalcMap((prev) => {
              if (!prev.has(product.id)) return prev;
              const next = new Map(prev);
              next.delete(product.id);
              return next;
            });
          }
        }
        setRowState(product.id, { status: "error", message });
        toast({
          variant: "destructive",
          title: `Ошибка сохранения: ${product.sku}`,
          description: message,
        });
      }
    },
    [hanger, recalcRow, recalcPairs, productPairs, setRowState],
  );

  const rows = useMemo(
    () => buildHangerCalcRows(products, calcMap, incompatible),
    [products, calcMap, incompatible],
  );

  const pairs = useMemo(
    () => resolvePairs(productPairs, pairProducts),
    [productPairs, pairProducts],
  );

  const pairedRows = useMemo(
    () => buildPairedHangerCalcRows(pairs, pairedCalcMap, pairedIncompatible),
    [pairs, pairedCalcMap, pairedIncompatible],
  );

  const allRows = useMemo(() => [...rows, ...pairedRows], [rows, pairedRows]);

  // Список значений каждой фильтруемой колонки берётся из описания: перебор
  // полей здесь означал бы, что шапка и список значений живут отдельно и
  // могут разойтись при добавлении колонки.
  const columnValues = useMemo(() => {
    const result: Partial<Record<HangerCalcSortField, string[]>> = {};
    for (const column of hangerCalcColumns) {
      const field = column.filterField;
      if (!field) continue;
      const values = [...new Set(allRows.map((row) => hangerCalcCellValue(row, field)))];
      result[field] = column.sortValues ? values.sort(column.sortValues) : values;
    }
    return result;
  }, [allRows]);

  const predicate = useMemo(
    () => buildFilterPredicate<HangerCalcRow | PairedHangerCalcRow>(hangerCalcCellValue),
    [buildFilterPredicate],
  );

  const visibleRows = useMemo(() => {
    const filtered = predicate ? allRows.filter(predicate) : allRows;
    const query = debouncedSearch.trim().toLocaleLowerCase("ru");
    const searched = query
      ? filtered.filter((row) =>
          rowSearchValues(row).some((value) =>
            value.toLocaleLowerCase("ru").includes(query),
          ),
        )
      : filtered;
    // Сортируется весь массив: сервер отдаёт по `sku` только одиночные строки,
    // парные приходят отдельным запросом и в общий порядок не попадали.
    return sortHangerCalcRows(searched, sortConfigs);
  }, [allRows, predicate, sortConfigs, debouncedSearch]);

  const resetFilters = resetAll;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-3">
        {hanger && <HangerConstantsPanel settings={hanger} />}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-52">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Поиск по артикулу"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
            {search && (
              <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
                <X className="h-4 w-4 text-muted-foreground" />
              </button>
            )}
          </div>
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              Сбросить фильтры
            </Button>
          )}
        </div>

        {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

        {/* Заглушка — только пока строк на экране не было ни разу. Перечитывание
            по сортировке не должно уносить дерево вместе с открытым поповером
            фильтра (ADR-0044). */}
        {loading && allRows.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
        ) : allRows.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm min-w-[1150px]">
              <thead>
                <tr>
                  {hangerCalcColumns.map((column) => (
                    <th
                      key={column.id}
                      className={cn(headerCellClass, column.headerClassName)}
                      aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                    >
                      <DataTableColumnHeader<HangerCalcSortField>
                        column={column}
                        bindColumn={bindColumn}
                        values={column.filterField ? columnValues[column.filterField] : undefined}
                        currentSorts={sortConfigs}
                        onSortChange={handleSort}
                      />
                    </th>
                  ))}
                  <TableCornerResetHeader
                    hasActiveFilters={hasActiveFilters}
                    onReset={resetFilters}
                    dataTableHeader
                  />
                </tr>
              </thead>
              <tbody className="divide-y">
                {visibleRows.map((row) =>
                  row.kind === "paired" ? (
                    <PairedHangerRowView key={`pair-${row.pairId}`} row={row} />
                  ) : (
                    <HangerCalcRowView
                      key={row.product.id}
                      row={row}
                      saveState={rowStates[row.product.id]}
                      readOnly={readOnly}
                      onEdit={onEdit}
                      onCommit={commitField}
                    />
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}


import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { toast } from "@/shared/ui/use-toast";
import { SortableFilterHeader } from "@/shared/ui/SortableFilterHeader";
import { TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useSortableColumnFilters } from "@/shared/hooks/useSortableColumnFilters";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { listProductsPaginated, patchProduct, getErrorMessage } from "@/shared/api/products";
import type { Product, ProductFilters } from "@/shared/api/products";
import { calcHanger, calcPairedHanger } from "@/shared/api/hangerCalc";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import { fetchAllTechcards } from "@/shared/api/techcards";
import type { Techcard } from "@/shared/api/techcards";
import { isHangerAutoMode, lengthKey, productLengths } from "@/shared/lib/hangerQuantity";
import {
  buildCalcItems,
  buildHangerCalcRows,
  buildPairedCalcItems,
  buildPairedHangerCalcRows,
  incompatibilityReason,
  resolvePairs,
  resultsToCalcMap,
  resultsToPairedCalcMap,
  rowSku,
  LIMITER_LABELS,
  type CalcMap,
  type HangerCalcRow,
  type PairedCalcMap,
  type PairedHangerCalcRow,
  type PairedPair,
} from "../lib/hangerCalcRows";
import { HangerConstantsPanel } from "./HangerConstantsPanel";
import { HangerCalcRowView, type RowSaveState } from "./HangerCalcRowView";
import { PairedHangerRowView } from "./PairedHangerRowView";

type CalcFilterField = "sku" | "total" | "limiter";

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
  const [pairedTechcards, setPairedTechcards] = useState<Techcard[]>([]);
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
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortConfigs, setSortConfigs] = useState<SortConfig<CalcFilterField>[]>([]);
  const {
    bindColumn,
    buildFilterPredicate,
    hasActiveColumnFilters,
    resetColumnFilters,
  } = useSortableColumnFilters<CalcFilterField>();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

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
    const query = debouncedSearch.trim();
    if (query) params.q = query;
    const activeSort = sortConfigs[0];
    if (activeSort && activeSort.field === "sku") {
      params.sort = `sku:${activeSort.order}`;
    }
    return params;
  }, [debouncedSearch, sortConfigs]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Полный набор компонентов нужен для пар, когда серверный поиск (q)
      // сужает одиночные строки: парная строка A+B не должна пропадать (#67).
      const [list, pairedList, constants, allComponents] = await Promise.all([
        listProductsPaginated(apiParams),
        fetchAllTechcards({ processing_type: "paired_processing", is_active: true }),
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

      // Парные строки A+B (#67): совместный расчёт по общим длинам пары.
      const pairs = resolvePairs(pairedList, pairProductsFull);
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
      setPairedTechcards(pairedList);
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

    if (!isHangerAutoMode(product)) {
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
    const resp = await calcHanger(
      lengths.map((lengthMm) => ({
        perimeter_mm: product.perimeter_mm,
        mount_width_mm: product.mount_width_mm,
        length_mm: lengthMm,
      })),
    );
    const byLength = new Map<string, HangerCalcResult>();
    resp.results.forEach((result, index) => {
      byLength.set(lengthKey(lengths[index]), result);
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
          await recalcPairs(resolvePairs(pairedTechcards, nextPairProducts), settings);
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
    [hanger, recalcRow, recalcPairs, pairedTechcards, setRowState],
  );

  const rows = useMemo(
    () => buildHangerCalcRows(products, calcMap, incompatible),
    [products, calcMap, incompatible],
  );

  const pairs = useMemo(
    () => resolvePairs(pairedTechcards, pairProducts),
    [pairedTechcards, pairProducts],
  );

  const pairedRows = useMemo(
    () => buildPairedHangerCalcRows(pairs, pairedCalcMap, pairedIncompatible),
    [pairs, pairedCalcMap, pairedIncompatible],
  );

  const allRows = useMemo(() => [...rows, ...pairedRows], [rows, pairedRows]);

  const uniqueValues = useMemo(
    () => ({
      sku: [
        ...new Set(
          allRows.map(rowSku),
        ),
      ].sort((a, b) => a.localeCompare(b, "ru")),
      total: [...new Set(allRows.map((r) => (r.total != null ? String(r.total) : "—")))].sort((a, b) => {
        if (a === "—") return 1;
        if (b === "—") return -1;
        return Number(a) - Number(b);
      }),
      limiter: [...new Set(allRows.map((r) => (r.limiter ? LIMITER_LABELS[r.limiter] : "—")))],
    }),
    [allRows],
  );

  const predicate = useMemo(
    () =>
      buildFilterPredicate<HangerCalcRow | PairedHangerCalcRow>((row, field) => {
        if (field === "sku") return rowSku(row);
        if (field === "total") return row.total != null ? String(row.total) : "—";
        return row.limiter ? LIMITER_LABELS[row.limiter] : "—";
      }),
    [buildFilterPredicate],
  );

  const visibleRows = useMemo(() => {
    // Поиск (q) и сортировка sku — на сервере (#84); фильтры total/limiter —
    // по вычисляемым полям расчёта (сервер их не знает, ADR-0014).
    const filtered = predicate ? allRows.filter(predicate) : allRows;
    if (sortConfigs.length === 0) return filtered;
    const hasServerSkuSort = sortConfigs.some((cfg) => cfg.field === "sku");
    const clientSorts = sortConfigs.filter((cfg) => cfg.field !== "sku");
    if (!hasServerSkuSort && clientSorts.length === 0) return filtered;
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      for (const cfg of clientSorts) {
        const av = sortAccessor(a, cfg.field);
        const bv = sortAccessor(b, cfg.field);
        let cmp = 0;
        if (av == null && bv == null) cmp = 0;
        else if (av == null) cmp = 1;
        else if (bv == null) cmp = -1;
        else if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv), "ru");
        if (cmp !== 0) return cfg.order === "asc" ? cmp : -cmp;
      }
      return 0;
    });
    return sorted;
  }, [allRows, predicate, sortConfigs]);

  const hasActiveFilters =
    search.trim().length > 0 || hasActiveColumnFilters || sortConfigs.length > 0;

  const resetFilters = () => {
    setSearch("");
    setSortConfigs([]);
    resetColumnFilters();
  };

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

        {loading ? (
          <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
        ) : allRows.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm min-w-[1150px]">
              <thead>
                <tr>
                  <th className={`${headerCellClass} p-0 min-w-48`}>
                    <SortableFilterHeader<CalcFilterField>
                      field="sku"
                      label="Артикул"
                      currentSorts={sortConfigs}
                      onSortChange={(field) => setSortConfigs((prev) => nextMultiSortConfigs(prev, field))}
                      values={uniqueValues.sku}
                      {...bindColumn("sku")}
                    />
                  </th>
                  <th className={`${headerCellClass} w-28`}>Периметр</th>
                  <th className={`${headerCellClass} w-28`}>Габарит</th>
                  <th className={`${headerCellClass} min-w-56`}>Длины → кол-во</th>
                  <th className={`${headerCellClass} w-24`}>По площади</th>
                  <th className={`${headerCellClass} w-24`}>По размеру</th>
                  <th className={`${headerCellClass} p-0 w-24`}>
                    <SortableFilterHeader<CalcFilterField>
                      field="total"
                      label="Итог"
                      currentSorts={sortConfigs}
                      onSortChange={(field) => setSortConfigs((prev) => nextMultiSortConfigs(prev, field))}
                      values={uniqueValues.total}
                      {...bindColumn("total")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 w-28`}>
                    <SortableFilterHeader<CalcFilterField>
                      field="limiter"
                      label="Лимитер"
                      currentSorts={sortConfigs}
                      onSortChange={(field) => setSortConfigs((prev) => nextMultiSortConfigs(prev, field))}
                      values={uniqueValues.limiter}
                      {...bindColumn("limiter")}
                    />
                  </th>
                  <th className={`${headerCellClass} w-28`}>м² на подвес</th>
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
                    <PairedHangerRowView
                      key={`pair-${row.techcardId}`}
                      row={row}
                      byLength={pairedCalcMap.get(row.techcardId)}
                    />
                  ) : (
                    <HangerCalcRowView
                      key={row.product.id}
                      row={row}
                      byLength={calcMap.get(row.product.id)}
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

function sortAccessor(
  row: HangerCalcRow | PairedHangerCalcRow,
  field: CalcFilterField,
): string | number | null {
  if (field === "sku") return rowSku(row);
  if (field === "total") return row.total;
  return row.limiter ? LIMITER_LABELS[row.limiter] : null;
}

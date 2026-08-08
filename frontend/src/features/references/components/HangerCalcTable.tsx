import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, X, Check, Loader2 } from "lucide-react";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Card } from "@/shared/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/shared/ui/tooltip";
import { toast } from "@/shared/ui/use-toast";
import { SortableFilterHeader } from "@/shared/ui/SortableFilterHeader";
import { TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useSortableColumnFilters } from "@/shared/hooks/useSortableColumnFilters";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { cn } from "@/shared/utils/cn";
import { listProductsPaginated, patchProduct, getErrorMessage } from "@/shared/api/products";
import type { Product } from "@/shared/api/products";
import { calcHanger } from "@/shared/api/hangerCalc";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import { entryForLength, isHangerAutoMode, lengthKey, productLengths } from "@/shared/lib/hangerQuantity";
import {
  buildCalcItems,
  buildHangerCalcRows,
  incompatibilityReason,
  resultsToCalcMap,
  LIMITER_LABELS,
  type CalcMap,
  type HangerCalcRow,
} from "../lib/hangerCalcRows";

type CalcFilterField = "sku" | "total" | "limiter";
type RowSaveState = { status: "saving" } | { status: "saved" } | { status: "error"; message: string };

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;
const chipClass = "inline-flex items-center rounded px-1.5 py-0.5 text-xs whitespace-nowrap";

function parseFieldValue(text: string): { ok: true; value: number | null } | { ok: false } {
  if (text.trim() === "") return { ok: true, value: null };
  const num = Number(text.replace(",", "."));
  if (!Number.isFinite(num) || num <= 0) return { ok: false };
  return { ok: true, value: num };
}

/** Inline-инпут периметра/габарита: autosave c дебаунсом, валидация >0 (#64, п. 16). */
function HangerFieldCell({
  value,
  disabled,
  rowInvalid,
  invalidReason,
  onCommit,
  ariaLabel,
}: {
  value: number | null;
  disabled: boolean;
  rowInvalid: boolean;
  invalidReason: string | null;
  onCommit: (next: number | null) => Promise<void>;
  ariaLabel: string;
}) {
  const savedText = value == null ? "" : String(value);
  const [draft, setDraft] = useState(savedText);
  const [invalid, setInvalid] = useState(false);
  const committing = useRef(false);

  useEffect(() => {
    setDraft(savedText);
    setInvalid(false);
  }, [savedText]);

  const parsed = parseFieldValue(draft);
  const dirty = draft !== savedText;

  useEffect(() => {
    if (!dirty) return;
    if (!parsed.ok) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if ((parsed.value ?? null) === (value ?? null)) return;
    const timer = window.setTimeout(() => {
      if (committing.current) return;
      committing.current = true;
      void onCommit(parsed.value).finally(() => {
        committing.current = false;
      });
    }, 700);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, parsed.ok]);

  const handleBlur = () => {
    if (committing.current) return;
    if (!dirty) return;
    if (!parsed.ok) {
      // Инвалидный draft (≤0) откатывается к сохранённому значению (#64).
      setDraft(savedText);
      setInvalid(false);
      return;
    }
    committing.current = true;
    void onCommit(parsed.value).finally(() => {
      committing.current = false;
    });
  };

  const highlighted = invalid || rowInvalid;
  return (
    <Input
      type="number"
      step="0.1"
      inputMode="decimal"
      aria-label={ariaLabel}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={handleBlur}
      onClick={(e) => e.stopPropagation()}
      disabled={disabled}
      className={cn(
        "h-8 w-24 min-w-24 text-sm bg-background",
        highlighted && "border-destructive focus-visible:ring-destructive",
      )}
      title={
        invalid
          ? "Значение должно быть больше 0 — сохранение заблокировано"
          : rowInvalid
            ? invalidReason ?? undefined
            : undefined
      }
    />
  );
}

function LengthChips({
  row,
  byLength,
}: {
  row: HangerCalcRow;
  byLength: Map<string, HangerCalcResult> | undefined;
}) {
  if (row.lengths.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {row.lengths.map((len) => {
        const key = lengthKey(len);
        if (!row.auto) {
          const manual = entryForLength(row.product.quantity_per_hanger, len)?.manual ?? null;
          return (
            <span key={key} className={cn(chipClass, "bg-secondary text-secondary-foreground")}>
              {len} мм → {manual ?? "—"} шт
            </span>
          );
        }
        if (row.incompatibleReason) {
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span className={cn(chipClass, "bg-red-100 text-red-700")}>{len} мм → —</span>
              </TooltipTrigger>
              <TooltipContent>{row.incompatibleReason}</TooltipContent>
            </Tooltip>
          );
        }
        const result = byLength?.get(key);
        if (!result || !result.is_calculable) {
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span className={cn(chipClass, "bg-amber-100 text-amber-800")}>{len} мм → —</span>
              </TooltipTrigger>
              <TooltipContent>Расчёт невозможен: не хватает данных</TooltipContent>
            </Tooltip>
          );
        }
        const limiterNote = result.limiter ? ` · ${LIMITER_LABELS[result.limiter]}` : "";
        return (
          <Tooltip key={key}>
            <TooltipTrigger asChild>
              <span className={cn(chipClass, "bg-secondary text-secondary-foreground cursor-help")}>
                {len} мм → {result.total ?? "—"} шт{limiterNote}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div className="text-xs space-y-0.5">
                <div className="font-medium">Длина {len} мм</div>
                <div>По площади: {result.by_area ?? "—"}</div>
                <div>По размеру: {result.by_size ?? "—"}</div>
                <div>Итог: {result.total ?? "—"}</div>
                <div>Лимитер: {result.limiter ? LIMITER_LABELS[result.limiter] : "—"}</div>
                <div>Площадь: {result.area_m2 != null ? `${result.area_m2.toFixed(3)} м²` : "—"}</div>
              </div>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

function DashCell({ reason, danger }: { reason: string | null; danger?: boolean }) {
  const dash = <span className={cn("text-muted-foreground", danger && "text-destructive")}>—</span>;
  if (!reason) return dash;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help">{dash}</span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

function HangerConstantsPanel({ settings }: { settings: HangerSettings }) {
  return (
    <Card className="p-3 text-sm">
      <div className="font-medium mb-1">Константы подвеса</div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
        <span>Лимит площади: <b className="text-foreground">{settings.area_limit_m2} м²</b></span>
        <span>Рабочая длина клюшки: <b className="text-foreground">{settings.rod_length_mm} мм</b></span>
        <span>Зазор: <b className="text-foreground">{settings.gap_mm} мм</b></span>
        <span>Клюшек на подвесе: <b className="text-foreground">×{settings.rod_count}</b></span>
      </div>
      <div className="text-xs text-muted-foreground mt-1.5">
        По площади = ⌊{settings.area_limit_m2} / (периметр × длина / 10⁶)⌋ · По размеру = ⌊
        {settings.rod_length_mm} / (габарит + {settings.gap_mm})⌋ × {settings.rod_count} · Итог = min
      </div>
    </Card>
  );
}

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
  const [hanger, setHanger] = useState<HangerSettings | null>(null);
  const [incompatible, setIncompatible] = useState<Map<number, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [truncated, setTruncated] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [rowStates, setRowStates] = useState<Record<number, RowSaveState | undefined>>({});
  const savedTimers = useRef<Map<number, number>>(new Map());

  const [search, setSearch] = useState("");
  const [sortConfigs, setSortConfigs] = useState<SortConfig<CalcFilterField>[]>([]);
  const {
    bindColumn,
    buildFilterPredicate,
    hasActiveColumnFilters,
    resetColumnFilters,
  } = useSortableColumnFilters<CalcFilterField>();

  const setRowState = useCallback((id: number, state: RowSaveState | undefined) => {
    setRowStates((prev) => ({ ...prev, [id]: state }));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, constants] = await Promise.all([
        listProductsPaginated({ type: "component", limit: 2000 }),
        calcHanger([]),
      ]);
      setTruncated(list.total > list.items.length);
      setTotalCount(list.total);
      const { items, refs, incompatible: incompatibles } = buildCalcItems(list.items, constants.hanger);
      let map: CalcMap = new Map();
      if (items.length > 0) {
        const resp = await calcHanger(items);
        map = resultsToCalcMap(refs, resp.results);
      }
      setProducts(list.items);
      setHanger(constants.hanger);
      setIncompatible(incompatibles);
      setCalcMap(map);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

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

  const commitField = useCallback(
    async (product: Product, field: "perimeter_mm" | "mount_width_mm", value: number | null) => {
      setRowState(product.id, { status: "saving" });
      try {
        const { data } = await patchProduct(product.id, { [field]: value });
        setProducts((prev) => prev.map((p) => (p.id === data.id ? data : p)));
        const settings = hanger;
        if (settings) await recalcRow(data, settings);
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
    [hanger, recalcRow, setRowState],
  );

  const rows = useMemo(
    () => buildHangerCalcRows(products, calcMap, incompatible),
    [products, calcMap, incompatible],
  );

  const uniqueValues = useMemo(
    () => ({
      sku: [...new Set(rows.map((r) => r.product.sku))].sort((a, b) => a.localeCompare(b, "ru")),
      total: [...new Set(rows.map((r) => (r.total != null ? String(r.total) : "—")))].sort((a, b) => {
        if (a === "—") return 1;
        if (b === "—") return -1;
        return Number(a) - Number(b);
      }),
      limiter: [...new Set(rows.map((r) => (r.limiter ? LIMITER_LABELS[r.limiter] : "—")))],
    }),
    [rows],
  );

  const predicate = useMemo(
    () =>
      buildFilterPredicate<HangerCalcRow>((row, field) => {
        if (field === "sku") return row.product.sku;
        if (field === "total") return row.total != null ? String(row.total) : "—";
        return row.limiter ? LIMITER_LABELS[row.limiter] : "—";
      }),
    [buildFilterPredicate],
  );

  const visibleRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (query && !row.product.sku.toLowerCase().includes(query)) return false;
      return predicate ? predicate(row) : true;
    });
    if (sortConfigs.length === 0) return filtered;
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      for (const cfg of sortConfigs) {
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
  }, [rows, search, predicate, sortConfigs]);

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

        {truncated && (
          <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 p-2 rounded-md">
            Показано {products.length} из {totalCount} артикулов. Используйте поиск для фильтрации.
          </div>
        )}

        {loading ? (
          <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
        ) : rows.length === 0 ? (
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
                {visibleRows.map((row) => (
                  <HangerCalcRowView
                    key={row.product.id}
                    row={row}
                    byLength={calcMap.get(row.product.id)}
                    saveState={rowStates[row.product.id]}
                    readOnly={readOnly}
                    onEdit={onEdit}
                    onCommit={commitField}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

function sortAccessor(row: HangerCalcRow, field: CalcFilterField): string | number | null {
  if (field === "sku") return row.product.sku;
  if (field === "total") return row.total;
  return row.limiter ? LIMITER_LABELS[row.limiter] : null;
}

function HangerCalcRowView({
  row,
  byLength,
  saveState,
  readOnly,
  onEdit,
  onCommit,
}: {
  row: HangerCalcRow;
  byLength: Map<string, HangerCalcResult> | undefined;
  saveState: RowSaveState | undefined;
  readOnly: boolean;
  onEdit: (product: Product) => void;
  onCommit: (product: Product, field: "perimeter_mm" | "mount_width_mm", value: number | null) => Promise<void>;
}) {
  const { product } = row;
  const rowInvalid = row.incompatibleReason != null;
  const primary = row.primaryResult;

  const breakdownReason = row.incompatibleReason
    ?? (!row.auto
      ? "Ручной режим: периметр или габарит не заполнены, расчёт не запускался"
      : row.primaryLength == null
        ? "Расчёт невозможен: у артикула нет длин"
        : !primary || !primary.is_calculable
          ? "Расчёт невозможен: не хватает данных"
          : null);

  // Единый guard для ячеек разбивки: авто, не инвалид, есть расчёт (#64 — dedup).
  const showBreakdown = row.auto && !rowInvalid && !!primary?.is_calculable;
  const isZeroTotal = showBreakdown && primary!.total === 0;
  const dashCell = <DashCell reason={breakdownReason} danger={rowInvalid} />;

  const totalCell = (() => {
    if (isZeroTotal) {
      return (
        <DashCell
          reason="Итог 0: профиль не помещается по лимитам — проверьте периметр и габарит"
          danger
        />
      );
    }
    if (showBreakdown) {
      return <span className="font-medium">{primary!.total}</span>;
    }
    if (!row.auto) {
      return row.total != null
        ? <span className="text-muted-foreground">{row.total}</span>
        : <DashCell reason={breakdownReason} />;
    }
    return dashCell;
  })();

  return (
    <tr className={cn("hover:bg-muted/50", rowInvalid && "bg-red-50 hover:bg-red-100/60")}>
      <td className="px-4 py-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            className="font-medium hover:underline text-left"
            onClick={() => onEdit(product)}
          >
            {product.sku}
          </button>
          {row.auto
            ? <Badge variant="secondary" className="text-xs bg-emerald-100">авто</Badge>
            : <Badge variant="secondary" className="text-xs">ручное</Badge>}
          {product.is_paired_profile && (
            <Badge variant="secondary" className="text-xs bg-purple-100">Парный</Badge>
          )}
        </div>
        {saveState?.status === "saving" && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
            <Loader2 className="h-3 w-3 animate-spin" /> сохраняется…
          </span>
        )}
        {saveState?.status === "saved" && (
          <span className="flex items-center gap-1 text-xs text-emerald-700 mt-0.5">
            <Check className="h-3 w-3" /> сохранено
          </span>
        )}
        {saveState?.status === "error" && (
          <span className="block text-xs text-destructive mt-0.5 max-w-56" title={saveState.message}>
            ошибка: {saveState.message}
          </span>
        )}
      </td>
      <td className="px-4 py-2">
        <HangerFieldCell
          value={product.perimeter_mm}
          disabled={readOnly}
          rowInvalid={rowInvalid}
          invalidReason={row.incompatibleReason}
          onCommit={(next) => onCommit(product, "perimeter_mm", next)}
          ariaLabel={`Периметр для ${product.sku}`}
        />
      </td>
      <td className="px-4 py-2">
        <HangerFieldCell
          value={product.mount_width_mm}
          disabled={readOnly}
          rowInvalid={rowInvalid}
          invalidReason={row.incompatibleReason}
          onCommit={(next) => onCommit(product, "mount_width_mm", next)}
          ariaLabel={`Габарит для ${product.sku}`}
        />
      </td>
      <td className="px-4 py-2">
        <LengthChips row={row} byLength={byLength} />
      </td>
      <td className="px-4 py-2">
        {showBreakdown ? primary!.by_area : dashCell}
      </td>
      <td className="px-4 py-2">
        {showBreakdown ? primary!.by_size : dashCell}
      </td>
      <td className="px-4 py-2">{totalCell}</td>
      <td className="px-4 py-2">
        {/* Итог 0: лимитер не печатается — противоречиво (#64). */}
        {showBreakdown && !isZeroTotal && primary!.limiter
          ? LIMITER_LABELS[primary!.limiter]
          : dashCell}
      </td>
      <td className="px-4 py-2">
        {showBreakdown && !isZeroTotal && primary!.area_m2 != null
          ? primary!.area_m2.toFixed(3)
          : dashCell}
      </td>
      <TableCornerResetCell />
    </tr>
  );
}

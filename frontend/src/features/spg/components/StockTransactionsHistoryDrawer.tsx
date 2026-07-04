import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import {
  Button,
  DateRangePicker,
  SortableFilterHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
  type DateRangeValue,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import {
  getStockTransactions,
  formatBalanceQtyInteger,
  formatQualityStateLabel,
  formatStockReasonLabel,
} from "@/shared/api/stock";
import type { StockTransactionEntry } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  useTableQueryEngine,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";

interface StockTransactionsHistoryDrawerProps {
  productId?: number;
  productSku?: string | null;
  locationId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type TransactionSortField = "date" | "reason" | "from" | "to" | "quantity" | "quality" | "comment";

function formatTxDate(createdAt: string | null): string {
  if (!createdAt) return "—";
  return new Date(createdAt).toLocaleString("ru-RU");
}

function formatTxQuality(tx: StockTransactionEntry): string {
  if (tx.from_quality_state !== tx.to_quality_state) {
    return `${formatQualityStateLabel(tx.from_quality_state)} → ${formatQualityStateLabel(tx.to_quality_state)}`;
  }
  return formatQualityStateLabel(tx.from_quality_state);
}

function getTxCellValue(tx: StockTransactionEntry, field: TransactionSortField): string {
  switch (field) {
    case "date":
      return formatTxDate(tx.created_at);
    case "reason":
      return formatStockReasonLabel(String(tx.reason), tx.source_ref);
    case "from":
      return tx.from_location_name || (tx.from_location_id ? `#${tx.from_location_id}` : "—");
    case "to":
      return tx.to_location_name || (tx.to_location_id ? `#${tx.to_location_id}` : "—");
    case "quantity":
      return formatBalanceQtyInteger(tx.quantity);
    case "quality":
      return formatTxQuality(tx);
    case "comment":
      return tx.comment || "—";
  }
}

export function StockTransactionsHistoryDrawer({
  productId,
  productSku,
  locationId,
  open,
  onOpenChange,
}: StockTransactionsHistoryDrawerProps) {
  const productLabel = productSku?.trim() || (productId !== undefined ? `#${productId}` : null);
  const [dateRange, setDateRange] = useState<DateRangeValue>({ from: "", to: "" });
  const hasDateFilter = Boolean(dateRange.from || dateRange.to);
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    setSortConfigs,
    handleSort: handleSortChange,
    hasActiveFilters,
    resetAll: handleResetFilters,
    resetColumnFilters,
  } = useFilterableTable<TransactionSortField>({
    extraHasActive: hasDateFilter,
    onExtraReset: () => setDateRange({ from: "", to: "" }),
  });

  useEffect(() => {
    if (!open) {
      setDateRange({ from: "", to: "" });
      setSortConfigs([]);
      resetColumnFilters();
    }
  }, [open, resetColumnFilters, setSortConfigs]);

  const { data: transactions = [], isLoading } = useQuery({
    queryKey: queryKeys.stock.transactions(
      JSON.stringify({ productId, locationId }),
    ),
    queryFn: () =>
      getStockTransactions({
        product_id: productId,
        location_id: locationId,
        limit: 500,
      }),
    enabled: open && productId !== undefined,
  });

  const dateFilteredTransactions = useMemo(() => {
    const { from, to } = dateRange;
    if (!from && !to) return transactions;
    return transactions.filter((tx) => {
      if (!tx.created_at) return false;
      const day = tx.created_at.slice(0, 10);
      if (from && day < from) return false;
      if (to && day > to) return false;
      return true;
    });
  }, [transactions, dateRange]);

  const sortDefs = useMemo((): ColumnSortDef<StockTransactionEntry, TransactionSortField>[] => [
    {
      field: "date",
      getSortValue: (tx) => (tx.created_at ? new Date(tx.created_at).getTime() : 0),
    },
    { field: "reason", getSortValue: (tx) => getTxCellValue(tx, "reason") },
    { field: "from", getSortValue: (tx) => getTxCellValue(tx, "from") },
    { field: "to", getSortValue: (tx) => getTxCellValue(tx, "to") },
    {
      field: "quantity",
      getSortValue: (tx) => Number.parseFloat(String(tx.quantity)) || 0,
    },
    { field: "quality", getSortValue: (tx) => getTxCellValue(tx, "quality") },
    { field: "comment", getSortValue: (tx) => getTxCellValue(tx, "comment") },
  ], []);

  const filterPredicate = useMemo(
    () => buildFilterPredicate(getTxCellValue),
    [buildFilterPredicate],
  );

  const uniqueValues = useMemo(() => ({
    date: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "date")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    reason: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "reason")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    from: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "from")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    to: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "to")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quantity: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "quantity")))].sort(
      (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
    ),
    quality: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "quality")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    comment: [...new Set(dateFilteredTransactions.map((tx) => getTxCellValue(tx, "comment")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
  }), [dateFilteredTransactions]);

  const { rows: filteredTransactions } = useTableQueryEngine<
    StockTransactionEntry,
    TransactionSortField
  >({
    rows: dateFilteredTransactions,
    getId: (tx) => tx.id,
    searchQuery: "",
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="fixed inset-0 bg-black/30" onClick={() => onOpenChange(false)} />
      <div className="relative w-full max-w-3xl bg-background shadow-xl border-l overflow-y-auto animate-in slide-in-from-right">
        <div className="sticky top-0 bg-background border-b z-10 px-4 py-3 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold min-w-0 truncate">
            {productLabel
              ? <>История движения по артикулу <span className="text-primary">{productLabel}</span></>
              : "История движения"}
          </h2>
          <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="p-4 space-y-4">
          <DateRangePicker
            from={dateRange.from}
            to={dateRange.to}
            onChange={setDateRange}
            className="w-full sm:w-auto sm:min-w-[280px] max-w-md"
            placeholder="Период"
            align="start"
          />

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : transactions.length === 0 ? (
            <div className="text-center py-12 text-sm text-muted-foreground border rounded-lg border-dashed">
              Транзакции не найдены
            </div>
          ) : (
            <div className="overflow-x-auto border rounded-lg">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="date"
                          label="Дата"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.date}
                          {...bindColumn("date")}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="reason"
                          label="Причина"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.reason}
                          {...bindColumn("reason")}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="from"
                          label="Откуда"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.from}
                          {...bindColumn("from")}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="to"
                          label="Куда"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.to}
                          {...bindColumn("to")}
                        />
                      </th>
                      <th className="p-2 text-right font-medium">
                        <SortableFilterHeader
                          field="quantity"
                          label="Кол-во"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quantity}
                          {...bindColumn("quantity")}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="quality"
                          label="Качество"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quality}
                          {...bindColumn("quality")}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="comment"
                          label="Комментарий"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.comment}
                          {...bindColumn("comment")}
                        />
                      </th>
                      <TableCornerResetHeader
                        hasActiveFilters={hasActiveFilters}
                        onReset={handleResetFilters}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTransactions.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="p-8 text-center text-sm text-muted-foreground">
                          Ничего не найдено по выбранным фильтрам
                        </td>
                      </tr>
                    ) : (
                    filteredTransactions.map((tx) => (
                      <tr key={tx.id} className="border-b hover:bg-muted/30">
                        <td className="p-2 text-xs whitespace-nowrap">
                          {formatTxDate(tx.created_at)}
                        </td>
                        <td className="p-2 text-xs font-medium">
                          {getTxCellValue(tx, "reason")}
                        </td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "from")}</td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "to")}</td>
                        <td className="p-2 text-right font-mono text-xs">
                          {getTxCellValue(tx, "quantity")}
                        </td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "quality")}</td>
                        <td className="p-2 text-xs text-muted-foreground max-w-[150px] truncate">
                          {getTxCellValue(tx, "comment")}
                        </td>
                        <TableCornerResetCell />
                      </tr>
                    )))}
                  </tbody>
                </table>
            </div>
          )}

          {!isLoading && transactions.length > 0 && (
            <div className="text-xs text-muted-foreground text-center">
              {filteredTransactions.length === dateFilteredTransactions.length
                ? `Показано ${filteredTransactions.length} записей`
                : `Показано ${filteredTransactions.length} из ${dateFilteredTransactions.length} записей`}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import {
  Button,
  DateRangePicker,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  type DateRangeValue,
} from "@/shared/ui";
import {
  getStockTransactions,
  formatBalanceQtyInteger,
  formatQualityStateLabel,
  formatStockReasonLabel,
  IMPORT_REMAINDERS_SOURCE_REF,
  toApiStockReason,
} from "@/shared/api/stock";
import type { StockReason } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";

interface StockTransactionsHistoryDrawerProps {
  productId?: number;
  locationId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const ALL_REASONS_VALUE = "all" as const;
const IMPORT_REASON_VALUE = "import_remainders" as const;

type ReasonFilterValue = StockReason | typeof ALL_REASONS_VALUE | typeof IMPORT_REASON_VALUE;

const REASON_OPTIONS: { value: ReasonFilterValue; label: string }[] = [
  { value: ALL_REASONS_VALUE, label: "Все причины" },
  { value: IMPORT_REASON_VALUE, label: "Импорт остатков" },
  { value: "MANUAL_IN", label: "Ручной приход" },
  { value: "MANUAL_OUT", label: "Ручной расход" },
  { value: "ADJUSTMENT_IN", label: "Корректировка +" },
  { value: "ADJUSTMENT_OUT", label: "Корректировка −" },
  { value: "ISSUE_TO_WORK", label: "Выдача в работу" },
  { value: "COMPLETE", label: "Выпуск" },
  { value: "TRANSFER_SEND", label: "Передача отправлено" },
  { value: "TRANSFER_RECEIVE", label: "Передача получено" },
  { value: "RETURN_TO_STOCK", label: "Возврат на склад" },
  { value: "SCRAP", label: "Брак" },
  { value: "REWORK", label: "Переделка" },
];

export function StockTransactionsHistoryDrawer({
  productId,
  locationId,
  open,
  onOpenChange,
}: StockTransactionsHistoryDrawerProps) {
  const [reasonFilter, setReasonFilter] = useState<ReasonFilterValue>(ALL_REASONS_VALUE);
  const [dateRange, setDateRange] = useState<DateRangeValue>({ from: "", to: "" });

  const { data: transactions = [], isLoading } = useQuery({
    queryKey: queryKeys.stock.transactions(
      JSON.stringify({
        productId,
        locationId,
        reason:
          reasonFilter === ALL_REASONS_VALUE || reasonFilter === IMPORT_REASON_VALUE
            ? undefined
            : reasonFilter,
      }),
    ),
    queryFn: () =>
      getStockTransactions({
        product_id: productId,
        location_id: locationId,
        reason:
          reasonFilter === ALL_REASONS_VALUE || reasonFilter === IMPORT_REASON_VALUE
            ? undefined
            : reasonFilter,
        limit: 500,
      }),
    enabled: open,
  });

  const filteredTransactions = useMemo(() => {
    let rows = transactions;

    if (reasonFilter === IMPORT_REASON_VALUE) {
      rows = rows.filter((tx) => tx.source_ref === IMPORT_REMAINDERS_SOURCE_REF);
    } else if (reasonFilter === "MANUAL_IN") {
      rows = rows.filter(
        (tx) =>
          toApiStockReason("MANUAL_IN") === String(tx.reason).toLowerCase()
          && tx.source_ref !== IMPORT_REMAINDERS_SOURCE_REF,
      );
    }

    const { from, to } = dateRange;
    if (!from && !to) return rows;
    return rows.filter((tx) => {
      if (!tx.created_at) return false;
      const day = tx.created_at.slice(0, 10);
      if (from && day < from) return false;
      if (to && day > to) return false;
      return true;
    });
  }, [transactions, dateRange, reasonFilter]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="fixed inset-0 bg-black/30" onClick={() => onOpenChange(false)} />
      <div className="relative w-full max-w-2xl bg-background shadow-xl border-l overflow-y-auto animate-in slide-in-from-right">
        <div className="sticky top-0 bg-background border-b z-10 px-4 py-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">История движения</h2>
          <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="p-4 space-y-4">
          {/* Filters */}
          <div className="flex flex-col sm:flex-row flex-wrap items-end gap-3">
            <div className="space-y-1 w-full sm:flex-1 sm:min-w-[200px]">
              <label className="text-xs font-medium text-muted-foreground">Причина</label>
              <Select
                value={reasonFilter}
                onValueChange={(val) => setReasonFilter(val as ReasonFilterValue)}
              >
                <SelectTrigger className="w-full h-9 text-sm bg-background">
                  <SelectValue placeholder="Все причины" />
                </SelectTrigger>
                <SelectContent>
                  {REASON_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DateRangePicker
              from={dateRange.from}
              to={dateRange.to}
              onChange={setDateRange}
              className="w-full sm:w-auto sm:min-w-[280px] max-w-md"
              placeholder="Выберите период"
              align="start"
            />
          </div>

          {/* Table */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredTransactions.length === 0 ? (
            <div className="text-center py-12 text-sm text-muted-foreground border rounded-lg border-dashed">
              {transactions.length === 0 ? "Транзакции не найдены" : "Нет транзакций за выбранный период"}
            </div>
          ) : (
            <div className="overflow-x-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 border-b">
                  <tr>
                    <th className="p-2 text-left font-medium">Дата</th>
                    <th className="p-2 text-left font-medium">Причина</th>
                    <th className="p-2 text-left font-medium">Откуда</th>
                    <th className="p-2 text-left font-medium">Куда</th>
                    <th className="p-2 text-right font-medium">Кол-во</th>
                    <th className="p-2 text-left font-medium">Качество</th>
                    <th className="p-2 text-left font-medium">Комментарий</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTransactions.map((tx) => (
                    <tr key={tx.id} className="border-b hover:bg-muted/30">
                      <td className="p-2 text-xs whitespace-nowrap">
                        {tx.created_at ? new Date(tx.created_at).toLocaleString("ru-RU") : "—"}
                      </td>
                      <td className="p-2 text-xs font-medium">
                        {formatStockReasonLabel(String(tx.reason), tx.source_ref)}
                      </td>
                      <td className="p-2 text-xs">
                        {tx.from_location_name
                          || (tx.from_location_id ? `#${tx.from_location_id}` : "—")}
                      </td>
                      <td className="p-2 text-xs">
                        {tx.to_location_name
                          || (tx.to_location_id ? `#${tx.to_location_id}` : "—")}
                      </td>
                      <td className="p-2 text-right font-mono text-xs">{formatBalanceQtyInteger(tx.quantity)}</td>
                      <td className="p-2 text-xs">
                        {tx.from_quality_state !== tx.to_quality_state
                          ? `${formatQualityStateLabel(tx.from_quality_state)} → ${formatQualityStateLabel(tx.to_quality_state)}`
                          : formatQualityStateLabel(tx.from_quality_state)}
                      </td>
                      <td className="p-2 text-xs text-muted-foreground max-w-[150px] truncate">
                        {tx.comment || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="text-xs text-muted-foreground text-center">
            {filteredTransactions.length === transactions.length
              ? `Показано ${transactions.length} записей`
              : `Показано ${filteredTransactions.length} из ${transactions.length} записей`}
          </div>
        </div>
      </div>
    </div>
  );
}

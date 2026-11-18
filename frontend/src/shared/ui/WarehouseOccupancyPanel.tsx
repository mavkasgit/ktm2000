import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import {
  getWarehouseOccupancy,
  type WarehouseOccupancyResponse,
  type WarehouseOccupancyRow,
} from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { cn } from "@/shared/utils/cn";

/**
 * Занятость складов в штуках (#350).
 *
 * Строка — склад, а не артикул: «в работе» / «свободно» / «всего» и общий
 * итог. Числа считает сервер (`GET /stock/occupancy`): `in_work + free =
 * total`, где `total` — физический годный остаток склада. Ёмкости в модели
 * нет, поэтому клиент ничего не досчитывает и не выдумывает.
 *
 * Раскладка — карточки в сетке, а не таблица: на 390×844 три числа остаются
 * в одной строке карточки и не требуют горизонтальной прокрутки.
 */

type OccupancyNumbers = Pick<WarehouseOccupancyRow, "in_work" | "free" | "total">;

function formatPieces(value: number): string {
  return `${fmtQty(value)} шт`;
}

function OccupancyMetrics({ numbers }: { numbers: OccupancyNumbers }) {
  return (
    <dl className="grid min-w-0 grid-cols-3 gap-2 text-center">
      <div className="min-w-0">
        <dt className="text-[11px] leading-tight text-muted-foreground">В работе</dt>
        <dd className="text-sm font-semibold tabular-nums">
          {formatPieces(numbers.in_work)}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-[11px] leading-tight text-muted-foreground">Свободно</dt>
        <dd className="text-sm font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
          {formatPieces(numbers.free)}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-[11px] leading-tight text-muted-foreground">Всего</dt>
        <dd className="text-sm font-semibold tabular-nums">
          {formatPieces(numbers.total)}
        </dd>
      </div>
    </dl>
  );
}

function WarehouseCard({ row }: { row: WarehouseOccupancyRow }) {
  return (
    <li className="min-w-0 rounded-lg border bg-card p-3">
      <div className="mb-2 flex min-w-0 items-baseline justify-between gap-2">
        <span className="truncate text-sm font-medium" title={row.warehouse}>
          {row.warehouse}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {row.warehouse_code}
        </span>
      </div>
      <OccupancyMetrics numbers={row} />
    </li>
  );
}

function TotalsCard({ totals }: { totals: OccupancyNumbers }) {
  return (
    <li className="min-w-0 rounded-lg border bg-muted/40 p-3 sm:col-span-2 xl:col-span-3">
      <div className="mb-2 text-sm font-medium">Итого по складам</div>
      <OccupancyMetrics numbers={totals} />
    </li>
  );
}

function OccupancyBody({ data }: { data: WarehouseOccupancyResponse }) {
  if (data.warehouses.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Складов-хранилищ нет — считать нечего.
      </p>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {data.warehouses.map((row) => (
        <WarehouseCard key={row.warehouse_id} row={row} />
      ))}
      <TotalsCard totals={data.totals} />
    </ul>
  );
}

export interface WarehouseOccupancyPanelProps {
  className?: string;
}

export function WarehouseOccupancyPanel({ className }: WarehouseOccupancyPanelProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.stock.occupancy(),
    queryFn: getWarehouseOccupancy,
  });

  return (
    <section aria-label="Занятость складов" className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold">Занятость складов</h2>
        <p className="text-xs text-muted-foreground">
          В работе и свободно — в штуках, по каждому складу
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка занятости складов...
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive" role="alert">
          Не удалось загрузить занятость складов
        </p>
      )}

      {data && <OccupancyBody data={data} />}
    </section>
  );
}

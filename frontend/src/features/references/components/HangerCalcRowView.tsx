import React from "react";
import { Check, Loader2 } from "lucide-react";
import { Badge } from "@/shared/ui/badge";
import { TableCornerResetCell } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { Product } from "@/shared/api/products";
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";
import { LIMITER_LABELS, type HangerCalcRow, type HangerLengthLine } from "../lib/hangerCalcRows";
import { DashCell } from "./DashCell";
import { HangerFieldCell } from "./HangerFieldCell";
import { HangerLineCell } from "./HangerLineCell";

export type RowSaveState = { status: "saving" } | { status: "saved" } | { status: "error"; message: string };

/** Причина нулевого итога подстроки: профиль не помещается по лимитам. */
const ZERO_TOTAL_REASON = "Итог 0: профиль не помещается по лимитам — проверьте периметр и габарит";

/** Пометка основной длины: её выбирает пользователь (ADR-0013). */
function PrimaryMark({ isPrimary }: { isPrimary: boolean }) {
  if (!isPrimary) return null;
  return <span className="ml-1.5 rounded bg-primary px-1 py-0.5 text-[10px] font-semibold text-primary-foreground">основная</span>;
}

/**
 * Строка таблицы «Расчёт подвесов»: одна на артикул, внутри — подстроки по
 * длинам (ADR-0050). Ячейки артикула, периметра и габарита принадлежат
 * артикулу и занимают всю строку, поэтому у них `rowSpan`; колонки длины и
 * разбивки печатают по подстроке, и своя разбивка у своей длины.
 */
export function HangerCalcRowView({
  row,
  saveState,
  readOnly,
  onEdit,
  onCommit,
}: {
  row: HangerCalcRow;
  saveState: RowSaveState | undefined;
  readOnly: boolean;
  onEdit: (product: Product) => void;
  onCommit: (product: Product, field: "perimeter_mm" | "mount_width_mm", value: number | null) => Promise<void>;
}) {
  const { product } = row;
  const rowInvalid = row.incompatibleReason != null;
  const span = row.lines.length;

  const totalCell = (line: HangerLengthLine) => {
    if (line.total === 0) return <DashCell reason={ZERO_TOTAL_REASON} danger />;
    if (line.total != null) return <span className="font-medium">{fmtQtyPrecise(line.total)}</span>;
    return <DashCell reason={line.totalReason} danger={rowInvalid} />;
  };
  // Разбивка печатается там, где у подстроки есть результат расчёта; в
  // ручном режиме его нет by design, и причину называет сама подстрока.
  const breakdownCell = (line: HangerLengthLine, value: number | null | undefined) =>
    line.result ? fmtQtyPrecise(value) : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;
  const limiterCell = (line: HangerLengthLine) =>
    line.result && line.total !== 0 && line.result.limiter
      ? LIMITER_LABELS[line.result.limiter]
      : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;
  const areaCell = (line: HangerLengthLine) =>
    line.result && line.total !== 0 && line.result.area_m2 != null
      ? line.result.area_m2.toFixed(3)
      : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;

  return (
    <tr className={cn("hover:bg-muted/50", rowInvalid && "bg-red-50 hover:bg-red-100/60")}>
      <td rowSpan={span} className="px-4 py-1 align-top">
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
      <td rowSpan={span} className="px-4 py-1 align-top">
        <HangerFieldCell
          value={product.perimeter_mm}
          disabled={readOnly}
          rowInvalid={rowInvalid}
          invalidReason={row.incompatibleReason}
          onCommit={(next) => onCommit(product, "perimeter_mm", next)}
          ariaLabel={`Периметр для ${product.sku}`}
        />
      </td>
      <td rowSpan={span} className="px-4 py-1 align-top">
        <HangerFieldCell
          value={product.mount_width_mm}
          disabled={readOnly}
          rowInvalid={rowInvalid}
          invalidReason={row.incompatibleReason}
          onCommit={(next) => onCommit(product, "mount_width_mm", next)}
          ariaLabel={`Габарит для ${product.sku}`}
        />
      </td>
      <HangerLineCell
        lines={row.lines}
        render={(line) => <span className="whitespace-nowrap">{line.lengthLabel}<PrimaryMark isPrimary={line.isPrimary} /></span>}
      />
      <HangerLineCell lines={row.lines} render={(line) => breakdownCell(line, line.result?.by_area)} />
      <HangerLineCell lines={row.lines} render={(line) => breakdownCell(line, line.result?.by_size)} />
      <HangerLineCell lines={row.lines} render={totalCell} />
      <HangerLineCell lines={row.lines} render={limiterCell} />
      <HangerLineCell lines={row.lines} render={areaCell} />
      <TableCornerResetCell />
    </tr>
  );
}

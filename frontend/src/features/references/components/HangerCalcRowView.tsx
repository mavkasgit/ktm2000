import React from "react";
import { Check, Loader2 } from "lucide-react";
import { Badge } from "@/shared/ui/badge";
import { TableCornerResetCell } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { Product } from "@/shared/api/products";
import type { HangerCalcResult } from "@/shared/api/hangerCalc";
import { LIMITER_LABELS, type HangerCalcRow } from "../lib/hangerCalcRows";
import { DashCell } from "./DashCell";
import { HangerFieldCell } from "./HangerFieldCell";
import { LengthChips } from "./LengthChips";

export type RowSaveState = { status: "saving" } | { status: "saved" } | { status: "error"; message: string };

export function HangerCalcRowView({
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

import { useMemo } from "react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { colorNameLabels } from "@/shared/lib/generated-labels";
import { adjustQtyToHanger, getQtyPerHanger } from "./PlanHangerDisplay";
import {
  buildPlanTaskGroups,
  type PlanTaskGroup,
  type PlanTaskGroupingMode,
  type PlanTaskRow,
} from "../lib/planTaskGroups";

interface PlanTaskTableProps {
  tasks: SectionBoardTask[];
  mode: PlanTaskGroupingMode;
  hiddenGroupKeys: Set<string>;
  onHideGroup: (groupKey: string) => void;
  printMode?: boolean;
}

function hangersForRow(row: PlanTaskRow): number | null {
  if (row.task.hanger_count != null) return row.task.hanger_count;
  const quantityPerHanger = row.task.quantity_per_hanger ?? getQtyPerHanger(row.task);
  if (quantityPerHanger == null) return null;
  return adjustQtyToHanger(row.planQty, quantityPerHanger).hangers;
}

function colorLabel(color: string | null): string {
  if (!color) return "—";
  return colorNameLabels[color] ?? color;
}

function operationsLabel(row: PlanTaskRow): string {
  if (row.preOperations.length === 0) return "—";
  return row.preOperations
    .map((operation) => operation.operation_name)
    .filter(Boolean)
    .join(" → ");
}

function packagingLabel(row: PlanTaskRow): string {
  const details = row.packagingDetails.length > 0 ? row.packagingDetails.join(" · ") : "";
  if (row.packaging && details) return `${row.packaging} · ${details}`;
  return row.packaging ?? (details || "—");
}

function sum(rows: PlanTaskRow[], field: "planQty" | "issuedQty" | "doneQty" | "transferredQty" | "balanceQty"): string {
  return rows.reduce((total, row) => total + row[field], 0).toFixed(0);
}

function sumHangers(rows: PlanTaskRow[]): string {
  const values = rows.map(hangersForRow).filter((value): value is number => value != null);
  return values.length === 0 ? "—" : String(values.reduce((total, value) => total + value, 0));
}

export function PlanTaskTable({
  tasks,
  mode,
  hiddenGroupKeys,
  onHideGroup,
  printMode = false,
}: PlanTaskTableProps) {
  const groups = useMemo(
    () => buildPlanTaskGroups(tasks, mode).filter((group) => !hiddenGroupKeys.has(group.key)),
    [tasks, mode, hiddenGroupKeys],
  );

  if (tasks.length === 0) {
    return <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">Нет данных</div>;
  }

  return (
    <div className={printMode ? "w-full" : "rounded-lg border overflow-x-auto"}>
      <table className="w-full text-sm border-collapse">
        <thead className="bg-gray-50">
          <tr className="border-b">
            <th className="px-3 py-2 text-left font-semibold">Группа</th>
            <th className="px-3 py-2 text-left font-semibold">Артикул</th>
            <th className="px-3 py-2 text-left font-semibold">Цвет</th>
            <th className="px-3 py-2 text-left font-semibold whitespace-nowrap">Размер</th>
            <th className="px-3 py-2 text-left font-semibold">Пред операции</th>
            <th className="px-3 py-2 text-left font-semibold">Операция</th>
            <th className="px-3 py-2 text-left font-semibold">Упаковка</th>
            <th className="px-3 py-2 text-right font-semibold">План</th>
            <th className="px-3 py-2 text-right font-semibold">Подвесы</th>
            <th className="px-3 py-2 text-right font-semibold">Выдано</th>
            <th className="px-3 py-2 text-right font-semibold">Сделано</th>
            <th className="px-3 py-2 text-right font-semibold">Передано</th>
            <th className="px-3 py-2 text-right font-semibold">Осталось</th>
            {!printMode && <th className="w-8" />}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <PlanGroupRows
              key={group.key}
              group={group}
              mode={mode}
              onHideGroup={onHideGroup}
              printMode={printMode}
            />
          ))}
          <tr className="border-t-2 font-semibold bg-gray-50">
            <td colSpan={7} className="px-3 py-2">Итого</td>
            <td className="px-3 py-2 text-right">{sum(groups.flatMap((group) => group.rows), "planQty")}</td>
            <td className="px-3 py-2 text-right">{sumHangers(groups.flatMap((group) => group.rows))}</td>
            <td className="px-3 py-2 text-right">{sum(groups.flatMap((group) => group.rows), "issuedQty")}</td>
            <td className="px-3 py-2 text-right">{sum(groups.flatMap((group) => group.rows), "doneQty")}</td>
            <td className="px-3 py-2 text-right">{sum(groups.flatMap((group) => group.rows), "transferredQty")}</td>
            <td className="px-3 py-2 text-right text-blue-700">{sum(groups.flatMap((group) => group.rows), "balanceQty")}</td>
            {!printMode && <td />}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function PlanGroupRows({
  group,
  mode,
  onHideGroup,
  printMode,
}: {
  group: PlanTaskGroup;
  mode: PlanTaskGroupingMode;
  onHideGroup: (groupKey: string) => void;
  printMode: boolean;
}) {
  return (
    <>
      <tr className="bg-slate-50 border-b">
        <td colSpan={7} className="px-3 py-2 font-semibold">
          {group.label}
          {mode === "anodizingColor" && <span className="ml-2 font-normal text-muted-foreground">Цвет: {colorLabel(group.rows[0]?.color ?? null)}</span>}
        </td>
        <td className="px-3 py-2 text-right font-semibold">{group.totalQtyPlan.toFixed(0)}</td>
        <td className="px-3 py-2 text-right font-semibold">{sumHangers(group.rows)}</td>
        <td className="px-3 py-2 text-right font-semibold">{group.totalQtyIssued.toFixed(0)}</td>
        <td className="px-3 py-2 text-right font-semibold">{group.totalQtyDone.toFixed(0)}</td>
        <td className="px-3 py-2 text-right font-semibold">{group.totalQtyTransferred.toFixed(0)}</td>
        <td className="px-3 py-2 text-right font-semibold text-blue-700">{(group.totalQtyPlan - group.totalQtyDone).toFixed(0)}</td>
        {!printMode && <td className="px-1 py-2 text-center"><button type="button" className="text-muted-foreground hover:text-red-600 text-lg leading-none" onClick={() => onHideGroup(group.key)} title="Скрыть группу">×</button></td>}
      </tr>
      {group.rows.map((row) => (
        <tr key={row.key} className="border-b hover:bg-gray-50">
          <td className="px-3 py-2 text-muted-foreground">↳</td>
          <td className="px-3 py-2 font-medium break-words">{row.task.product_sku}</td>
          <td className="px-3 py-2 whitespace-nowrap">{colorLabel(row.color)}</td>
          <td className="px-3 py-2 whitespace-nowrap">{formatDimensionsLabel(row.dimensions)}</td>
          <td className="px-3 py-2 max-w-[220px]">{operationsLabel(row)}</td>
          <td className="px-3 py-2 max-w-[180px] break-words">{row.task.operation_name || "Операция"}</td>
          <td className="px-3 py-2 max-w-[220px] break-words">{packagingLabel(row)}</td>
          <td className="px-3 py-2 text-right">{row.planQty.toFixed(0)}</td>
          <td className="px-3 py-2 text-right">{hangersForRow(row) ?? "—"}</td>
          <td className="px-3 py-2 text-right">{row.issuedQty.toFixed(0)}</td>
          <td className="px-3 py-2 text-right">{row.doneQty.toFixed(0)}</td>
          <td className="px-3 py-2 text-right">{row.transferredQty.toFixed(0)}</td>
          <td className="px-3 py-2 text-right text-blue-700 font-semibold">{row.balanceQty.toFixed(0)}</td>
          {!printMode && <td />}
        </tr>
      ))}
    </>
  );
}

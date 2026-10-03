import { useMemo } from "react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { QTY_EMPTY, fmtQty, fmtQtyPrecise } from "@/shared/lib/quantityFormat";
import { getQtyPerHanger } from "./PlanHangerDisplay";
import { countHangers } from "@/shared/lib/hangerCount";
import {
  buildPlanTaskGroups,
  type PlanPairIndex,
  type PlanTaskGroup,
  type PlanTaskGroupingMode,
  type PlanTaskRow,
} from "../lib/planTaskGroups";
import { packagingLabel } from "../lib/taskView";
import { PLAN_COLUMNS, type PlanColumnKey } from "../lib/planPrintSettings";
import { cn } from "@/shared/utils/cn";

interface PlanTaskTableProps {
  tasks: SectionBoardTask[];
  mode: PlanTaskGroupingMode;
  hiddenGroupKeys: Set<string>;
  onHideGroup: (groupKey: string) => void;
  /** Печатный набор колонок; служебные колонки окна добавляются автоматически. */
  columns: PlanColumnKey[];
  /** Пары сырьевых артикулов по `product_id` (#312): строки одной пары печатаются
   *  единым подвесом. Не передан — печать как раньше, каждая позиция своя. */
  pairs?: PlanPairIndex;
}

/**
 * Подвесы задания: готовый `hanger_count` бэкенда, иначе канон
 * `countHangers`. Нормы нет или количество неположительное — значения нет
 * (`null`), а не «1 подвес»: в печатном листе это `—`.
 */
function hangersForTask(task: SectionBoardTask): number | null {
  if (task.hanger_count != null) return task.hanger_count;
  return countHangers(task.planned_quantity, task.quantity_per_hanger ?? getQtyPerHanger(task));
}

/**
 * Подвесы строки — сумма по объединённым заданиям. Пропуск не превращается в
 * ноль молча: если хотя бы у одного задания нормы нет, сумма строки тоже
 * неизвестна, иначе в печати вышел бы заниженный итог как настоящий.
 */
function hangersForRow(row: PlanTaskRow): number | null {
  if (row.tasks.length === 0) return null;
  let total = 0;
  for (const task of row.tasks) {
    const hangers = hangersForTask(task);
    if (hangers === null) return null;
    total += hangers;
  }
  return total;
}

/**
 * Норма на подвес задания: ручной override из payload → пара (`product_pair`)
 * → норма позиции. Тот же приоритет, что и при подсчёте подвесов.
 * Норма не суммируется: в объединённой строке показываются разные значения.
 */
function perHangerForRows(rows: PlanTaskRow[]): string {
  const values: string[] = [];
  for (const row of rows) {
    for (const task of row.tasks) {
      const perHanger = getQtyPerHanger(task) ?? task.quantity_per_hanger;
      if (perHanger == null) continue;
      const text = fmtQtyPrecise(perHanger);
      if (!values.includes(text)) values.push(text);
    }
  }
  return values.length === 0 ? QTY_EMPTY : values.join(" / ");
}

function perHangerForRow(row: PlanTaskRow): string {
  return perHangerForRows([row]);
}

function colorLabel(color: string | null): string {
  return color || QTY_EMPTY;
}

function operationsLabel(row: PlanTaskRow): string {
  if (row.preOperations.length === 0) return QTY_EMPTY;
  return row.preOperations
    .map((operation) => operation.operation_name)
    .filter(Boolean)
    .join(" → ");
}


const cellBase = "px-3 py-2";

/**
 * Служебная колонка отметки строки внутри группы («↳»). Заголовка у неё нет, и
 * она уже печатных колонок: подпись «Группа» была самой широкой её частью, а
 * при растяжке таблицы на всю ширину окна забирала больше всех пустого места.
 *
 * На печать колонка выводится (`no-print-col` на ней нет): заголовок группы
 * объединяет метки через `colSpan` и на бумаге считается по тем же колонкам,
 * что и строки, — спрятанная колонка сдвинула бы итоги группы на колонку
 * вправо.
 */
const GROUP_MARKER_CELL = "w-7 px-1 py-2";

/** Ячейка колонки в строке задания. */
function rowCell(row: PlanTaskRow, key: PlanColumnKey, single: boolean) {
  switch (key) {
    case "group":
      return <td key={key} className={cn(GROUP_MARKER_CELL, "text-muted-foreground")}>{single ? "" : "↳"}</td>;
    case "sku":
      return <td key={key} className={cn(cellBase, "font-medium break-words")}>{row.productSku}</td>;
    case "size":
      return <td key={key} className={cn(cellBase, "whitespace-nowrap")}>{formatDimensionsLabel(row.dimensions)}</td>;
    case "preOps":
      return <td key={key} className={cn(cellBase, "max-w-[220px]")}>{operationsLabel(row)}</td>;
    case "operation":
      return <td key={key} className={cn(cellBase, "max-w-[180px] break-words")}>{row.operationName}</td>;
    case "packaging":
      return <td key={key} className={cn(cellBase, "max-w-[220px] break-words")}>{packagingLabel(row.packaging, fmtQty)}</td>;
    case "hangers":
      return <td key={key} className={cn(cellBase, "text-right")}>{hangersForRow(row) ?? QTY_EMPTY}</td>;
    case "perHanger":
      return <td key={key} className={cn(cellBase, "text-right whitespace-nowrap")}>{perHangerForRow(row)}</td>;
    case "issued":
      return <td key={key} className={cn(cellBase, "text-right")}>{fmtQty(row.issuedQty)}</td>;
    case "done":
      return <td key={key} className={cn(cellBase, "text-right")}>{fmtQty(row.doneQty)}</td>;
    case "transferred":
      return <td key={key} className={cn(cellBase, "text-right")}>{fmtQty(row.transferredQty)}</td>;
    case "balance":
      return <td key={key} className={cn(cellBase, "text-right text-blue-700 font-semibold")}>{fmtQty(row.balanceQty)}</td>;
    case "actions":
      return <td key={key} className="no-print-col" />;
  }
}

/** Числовая ячейка в строке группы. */
function aggregateCell(
  key: PlanColumnKey,
  value: number,
  accent: boolean,
) {
  return (
    <td key={key} className={cn(cellBase, "text-right font-semibold", accent && "text-blue-700")}>
      {fmtQty(value)}
    </td>
  );
}

/**
 * Подвесы группы — сумма по строкам. Строка с пропуском делает сумму группы
 * неизвестной: частичный итог в шапке читался бы как настоящий, но был бы
 * занижен. Все строки известны — сумма; хотя бы одна нет — `—`.
 *
 * Группа пары — исключение: обе позиции печатаются ОДНИМ подвесом (#312),
 * поэтому подвесы не складываются, а берутся у пары. Сумма дала бы удвоенный
 * итог и на бумаге вышел бы подвес, которого физически нет.
 */
function sumHangers(rows: PlanTaskRow[]): number | null {
  if (rows.length === 0) return null;
  let total = 0;
  for (const row of rows) {
    const hangers = hangersForRow(row);
    if (hangers === null) return null;
    total += hangers;
  }
  return total;
}

/**
 * Подвесы группы. Группа пары — исключение: обе позиции печатаются ОДНИМ
 * подвесом (#312), поэтому подвесы не складываются, а берутся у пары. Сумма
 * дала бы удвоенный итог, и на бумаге вышел бы подвес, которого нет.
 */
function groupHangers(group: PlanTaskGroup): number | null {
  if (group.pair) {
    const perHanger = group.pair.quantityPerHanger;
    if (perHanger != null && perHanger > 0) {
      // Подвес заполняется парой целиком, поэтому количество берётся по
      // большей из позиций: лишнее место второй позиции подвес не занимает.
      const quantity = Math.max(...group.rows.map((row) => row.planQty), 0);
      if (quantity > 0) return Math.ceil(quantity / perHanger);
    }
    return null;
  }
  return sumHangers(group.rows);
}

/** Норма на подвес группы пары: `N×A + N×B`, иначе — нормы строк. */
function groupPerHanger(group: PlanTaskGroup): string {
  if (group.pair?.quantityPerHanger != null && group.pair.quantityPerHanger > 0) {
    const n = fmtQtyPrecise(group.pair.quantityPerHanger);
    return group.pair.skus.map((sku) => `${n}×${sku}`).join(" + ");
  }
  return perHangerForRows(group.rows);
}

export function PlanTaskTable({
  tasks,
  mode,
  hiddenGroupKeys,
  onHideGroup,
  columns,
  pairs,
}: PlanTaskTableProps) {
  const groups = useMemo(
    () => buildPlanTaskGroups(tasks, mode, pairs).filter((group) => !hiddenGroupKeys.has(group.key)),
    [tasks, mode, hiddenGroupKeys, pairs],
  );

  /** Выбранные печатные колонки + служебные колонки окна, в порядке определения. */
  const active = useMemo(() => {
    const selected = new Set(columns);
    return PLAN_COLUMNS.filter(
      (column) => column.service || selected.has(column.key),
    );
  }, [columns]);

  const labelSpan = useMemo(
    () => active.filter((column) => column.kind === "label").length,
    [active],
  );

  if (tasks.length === 0) {
    return <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">Нет данных</div>;
  }

  return (
    <div className="mx-auto w-fit max-w-full rounded-lg border overflow-x-auto">
      {/* Ширину задаёт содержимое, и растёт она от центра: `w-fit` + `mx-auto`
          держат таблицу по центру листа, а не прижимают её к левому краю
          пустой страницы. Набор из двух колонок иначе растягивался на всю
          ширину окна и разводил артикул и остаток полутора метрами пустоты.
          Много колонок — блок упирается в ширину листа и прокручивается
          (`overflow-x-auto`), поэтому `max-w-full`.
          На печати ширину превью держит `fit-table`: без него лист растягивал
          таблицу на себя (`width: 100%` с `table-layout: fixed`), и бумага
          расходилась с окном — колонки в превью стояли по содержимому, на
          листе разъезжались от края до края. */}
      <table className="fit-table text-sm border-collapse">
        <thead className="bg-gray-50">
          <tr className="border-b">
            {active.map((column) => (
              <th
                key={column.key}
                className={cn(
                  column.key === "group" ? GROUP_MARKER_CELL : cellBase,
                  "font-semibold",
                  column.kind === "number" ? "text-right" : "text-left",
                  column.key === "size" && "whitespace-nowrap",
                  column.service && column.key !== "group" && "no-print-col",
                  column.key === "actions" && "w-8",
                )}
              >
                {/* Служебные колонки окна в шапке не подписываются: у «Группы»
                    заголовок был самой широкой её частью, а сама колонка —
                    только отметкой строки внутри группы. */}
                {column.service ? null : column.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <PlanGroupRows
              key={group.key}
              group={group}
              mode={mode}
              onHideGroup={onHideGroup}
              active={active}
              labelSpan={labelSpan}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanGroupRows({
  group,
  mode,
  onHideGroup,
  active,
  labelSpan,
}: {
  group: PlanTaskGroup;
  mode: PlanTaskGroupingMode;
  onHideGroup: (groupKey: string) => void;
  active: typeof PLAN_COLUMNS;
  labelSpan: number;
}) {
  // Группа из одной строки не дублируется заголовком: строка и есть группа.
  const single = group.rows.length === 1;

  return (
    <>
      {!single && (
        <tr className="bg-slate-50 border-b">
          <td colSpan={labelSpan} className={cn(cellBase, "font-semibold")}>
            {group.label}
            {mode === "anodizingColor" && <span className="ml-2 font-normal text-muted-foreground">Цвет: {colorLabel(group.rows[0]?.color ?? null)}</span>}
          </td>
          {active
            .filter((column) => column.kind === "number")
            .map((column) => {
              switch (column.key) {
                case "hangers": {
                  const hangers = groupHangers(group);
                  return (
                    <td key={column.key} className={cn(cellBase, "text-right font-semibold")}>
                      {hangers ?? QTY_EMPTY}
                    </td>
                  );
                }
                case "perHanger":
                  return (
                    <td key={column.key} className={cn(cellBase, "text-right font-semibold whitespace-nowrap")}>
                      {groupPerHanger(group)}
                    </td>
                  );
                case "issued":
                  return aggregateCell(column.key, group.totalQtyIssued, false);
                case "done":
                  return aggregateCell(column.key, group.totalQtyDone, false);
                case "transferred":
                  return aggregateCell(column.key, group.totalQtyTransferred, false);
                case "balance":
                  return aggregateCell(column.key, group.totalQtyPlan - group.totalQtyDone, true);
                case "actions":
                  return (
                    <td key={column.key} className={cn(cellBase, "px-1 py-2 text-center no-print-col")}>
                      <button type="button" className="text-muted-foreground hover:text-red-600 text-lg leading-none" onClick={() => onHideGroup(group.key)} title="Скрыть группу">×</button>
                    </td>
                  );
              }
            })}
        </tr>
      )}
      {group.rows.map((row) => (
        <tr key={row.key} className="border-b hover:bg-gray-50">
          {active.map((column) => rowCell(row, column.key, single))}
        </tr>
      ))}
    </>
  );
}

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { SortableFilterHeader, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { listSections } from "@/shared/api/sections";
import { queryKeys } from "@/shared/api/queryKeys";
import { fmtQty } from "@/shared/utils/fmtQty";
import { isStorageType } from "@/shared/lib/routeStageClassifier";
import { type ProductionPlanningStage } from "@/shared/api/productionPlans";
import { stageStatusLabels } from "@/shared/lib/generated-labels";
import {
  useTableQueryEngine,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";

type StageSortField = "section" | "status";
type StageRowTone = "current" | "completed" | "partial" | "default";

const ROW_TONE_CLASS: Record<StageRowTone, string> = {
  current: "bg-blue-50/90 hover:bg-blue-50",
  completed: "bg-emerald-50/70 hover:bg-emerald-50/90",
  partial: "bg-amber-50/70 hover:bg-amber-50/90",
  default: "hover:bg-muted/25",
};

interface ExecutionStagesTableProps {
  stages: ProductionPlanningStage[];
  currentStageSectionId?: number | null;
  currentStageSequence?: number | null;
}

function getStageSectionLabel(stage: ProductionPlanningStage): string {
  return stage.section_name || stage.section_code || "—";
}

function getStageStatusLabel(stage: ProductionPlanningStage, isFinalStage: boolean): string {
  const base = stageStatusLabels[stage.task_status] || stage.task_status;
  return isFinalStage ? `${base} (финальный этап)` : base;
}

function getStageRowTone(
  stage: ProductionPlanningStage,
  opts: { isCurrentStage: boolean; currentStageSequence: number | null },
): StageRowTone {
  if (opts.isCurrentStage) return "current";

  const planned = stage.planned_quantity;
  const accounted = stage.accounted_total_qty;
  const hasActivity =
    stage.issued_qty > 0 || stage.accounted_total_qty > 0 || stage.sent_qty > 0 || stage.completed_quantity > 0;

  if (stage.task_status === "completed" || (planned > 0 && accounted >= planned)) {
    return "completed";
  }

  if (
    stage.task_status === "partially_completed" ||
    stage.task_status === "in_progress" ||
    (hasActivity && planned > 0 && accounted < planned)
  ) {
    return "partial";
  }

  if (
    opts.currentStageSequence !== null &&
    stage.sequence < opts.currentStageSequence &&
    (stage.sent_qty > 0 || stage.task_status === "completed")
  ) {
    return "completed";
  }

  return "default";
}

function QtyCell({ value }: { value: number }) {
  const text = fmtQty(value);
  return (
    <td className={`px-2 py-1.5 text-right align-top tabular-nums ${value === 0 ? "text-muted-foreground/70" : ""}`}>
      {text}
    </td>
  );
}

function StorageSkipCell() {
  return (
    <td className="px-2 py-1.5 text-right align-top text-muted-foreground/40">
      —
    </td>
  );
}

function resolveTransferOnlyStage(
  stage: ProductionPlanningStage,
  sectionType?: string | null,
): boolean {
  return isStorageType(stage.section_type ?? sectionType);
}

function getStageProgressPercent(
  stage: ProductionPlanningStage,
  isTransferOnly: boolean,
): string {
  if (stage.planned_quantity <= 0) return "0.0";
  if (isTransferOnly) {
    const issued = Math.max(stage.sent_qty, stage.transferred_quantity);
    return ((issued / stage.planned_quantity) * 100).toFixed(1);
  }
  const produced = Math.max(stage.accounted_good_qty, stage.completed_quantity);
  return ((produced / stage.planned_quantity) * 100).toFixed(1);
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;
const numHeaderClass = `${headerCellClass} text-right whitespace-nowrap`;

export function ExecutionStagesTable({
  stages,
  currentStageSectionId,
  currentStageSequence = null,
}: ExecutionStagesTableProps) {
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    handleSort: handleSortChange,
    hasActiveFilters,
    resetAll: handleResetFilters,
  } = useFilterableTable<StageSortField>();

  const { data: sectionsData } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: listSections,
  });

  const sectionMetaById = useMemo(() => {
    const map = new Map<number, { icon: string | null; icon_color: string | null; type: string }>();
    (sectionsData || []).forEach((s) =>
      map.set(s.id, { icon: s.icon, icon_color: s.icon_color, type: s.type }),
    );
    return map;
  }, [sectionsData]);

  const isTransferOnlyStage = useCallback(
    (stage: ProductionPlanningStage) =>
      resolveTransferOnlyStage(stage, sectionMetaById.get(stage.section_id)?.type),
    [sectionMetaById],
  );

  const stageRows = useMemo(
    () =>
      stages.map((stage, idx) => {
        const isCurrentStage = Boolean(currentStageSectionId && stage.section_id === currentStageSectionId);
        return {
          stage,
          isFinalStage: idx === stages.length - 1,
          isCurrentStage,
          tone: getStageRowTone(stage, { isCurrentStage, currentStageSequence }),
        };
      }),
    [stages, currentStageSectionId, currentStageSequence],
  );

  const getCellValue = useCallback(
    (row: (typeof stageRows)[number], field: StageSortField): string => {
      if (field === "section") return getStageSectionLabel(row.stage);
      return getStageStatusLabel(row.stage, row.isFinalStage);
    },
    [],
  );

  const sortDefs = useMemo((): ColumnSortDef<(typeof stageRows)[number], StageSortField>[] => [
    { field: "section", getSortValue: (row) => getCellValue(row, "section") },
    { field: "status", getSortValue: (row) => getCellValue(row, "status") },
  ], [getCellValue]);

  const filterPredicate = useMemo(
    () => buildFilterPredicate(getCellValue),
    [buildFilterPredicate, getCellValue],
  );

  const uniqueValues = useMemo(
    () => ({
      section: [...new Set(stageRows.map((row) => getCellValue(row, "section")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      status: [...new Set(stageRows.map((row) => getCellValue(row, "status")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
    }),
    [stageRows, getCellValue],
  );

  const { rows: filteredRows } = useTableQueryEngine({
    rows: stageRows,
    getId: (row) => row.stage.route_step_id,
    searchQuery: "",
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  if (stages.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground text-center border rounded-lg">
        Маршрутные этапы отсутствуют
      </p>
    );
  }

  return (
    <div className={`${DATA_TABLE_STYLES.container} max-h-[min(70vh,520px)]`}>
      <table className="w-full text-sm border-separate border-spacing-0">
        <thead>
          <tr>
            <th className={`${headerCellClass} w-14`}>Этап</th>
            <th className={`${headerCellClass} p-0 min-w-[140px]`}>
              <SortableFilterHeader
                field="section"
                label="Участок"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.section}
                {...bindColumn("section")}
              />
            </th>
            <th className={`${headerCellClass} p-0 min-w-[120px]`}>
              <SortableFilterHeader
                field="status"
                label="Статус этапа"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.status}
                {...bindColumn("status")}
              />
            </th>
            <th className={numHeaderClass}>План</th>
            <th className={numHeaderClass} title="Пришло с предыдущего этапа">
              Получено
            </th>
            <th className={numHeaderClass} title="Годные">Годные</th>
            <th className={numHeaderClass} title="Брак">Брак</th>
            <th className={numHeaderClass} title="Выдано на следующий этап">
              Выдано
            </th>
            <th className={numHeaderClass}>Остаток</th>
            <th className={numHeaderClass} title="Склад: выдано/план, производство: годные/план">%</th>
            <TableCornerResetHeader
              hasActiveFilters={hasActiveFilters}
              onReset={handleResetFilters}
              dataTableHeader
            />
          </tr>
        </thead>
        <tbody>
          {filteredRows.map(({ stage, isFinalStage, tone }) => {
            const isTransferOnly = isTransferOnlyStage(stage);
            const pct = getStageProgressPercent(stage, isTransferOnly);
            const sectionMeta = sectionMetaById.get(stage.section_id);
            const stageIcon = stage.section_icon || sectionMeta?.icon || null;
            const iconColor = stage.section_icon_color || sectionMeta?.icon_color || "#2563EB";
            const stageStatusText = getStageStatusLabel(stage, isFinalStage);
            const receivedQty = stage.issued_qty;
            const issuedQty = Math.max(stage.sent_qty, stage.transferred_quantity);
            const remainingQty = isTransferOnly
              ? Math.max(
                  (receivedQty > 0 ? receivedQty : stage.planned_quantity) - issuedQty,
                  0,
                )
              : Math.max(stage.planned_quantity - stage.accounted_total_qty, 0);

            return (
              <tr
                key={stage.route_step_id}
                className={`border-b border-border/60 transition-colors ${ROW_TONE_CLASS[tone]}`}
              >
                <td className="px-2 py-1.5 align-top tabular-nums text-muted-foreground">
                  #{stage.sequence}
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-2 min-w-0">
                    {stageIcon && (
                      <span
                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded"
                        style={{ backgroundColor: `${iconColor}18`, color: iconColor }}
                      >
                        {renderIcon(stageIcon, "h-4 w-4")}
                      </span>
                    )}
                    <span className="font-medium truncate">{stage.section_name}</span>
                  </div>
                </td>
                <td className="px-2 py-1.5 align-top text-xs text-muted-foreground">
                  {stageStatusText}
                </td>
                <QtyCell value={stage.planned_quantity} />
                <QtyCell value={receivedQty} />
                {isTransferOnly ? (
                  <>
                    <StorageSkipCell />
                    <StorageSkipCell />
                  </>
                ) : (
                  <>
                    <QtyCell value={stage.accounted_good_qty} />
                    <QtyCell value={stage.accounted_reject_qty} />
                  </>
                )}
                <QtyCell value={issuedQty} />
                <QtyCell value={remainingQty} />
                <td className={`px-2 py-1.5 text-right align-top tabular-nums ${Number(pct) === 0 ? "text-muted-foreground/70" : ""}`}>
                  {pct}%
                </td>
                <TableCornerResetCell />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
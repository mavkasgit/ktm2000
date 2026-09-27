import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createRef } from "react";

import type { ProductionPlanningRow } from "@/shared/api/productionPlans";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";

import { ExecutionTable } from "./ExecutionTable";
import { getExecutionTableColumns } from "./execution-table-columns";
import type { ExecutionSortField } from "./execution-utils";

/**
 * Шапка обещает сортировку ровно там, где сервер её выполнит: колонки,
 * которых нет в `ROWS_SORT_FIELDS` бэкенда, не должны показывать кнопку
 * сортировки, иначе пользователь кликает иконку и порядок строк не меняется.
 */
function Harness({ sortConfigs }: { sortConfigs: { field: ExecutionSortField; order: "asc" | "desc" }[] }) {
  const { bindColumn } = useFilterableTable<ExecutionSortField>();

  return (
    <ExecutionTable
      rows={[] as ProductionPlanningRow[]}
      isLoading={false}
      bulkMode={false}
      totalRows={0}
      releasedRows={0}
      completedRows={0}
      filterFields={[]}
      activeFilterSummary={{ count: 0, labels: [] }}
      tableHasActiveFilters={false}
      sortConfigs={sortConfigs}
      handleSortChange={vi.fn()}
      getAriaSort={(field) => {
        const active = sortConfigs.find((config) => config.field === field);
        if (!active) return "none" as const;
        return active.order === "asc" ? ("ascending" as const) : ("descending" as const);
      }}
      bindColumn={bindColumn}
      uniqueValuesByField={{
        id: [],
        row: [],
        plan: [],
        sku: [],
        name: [],
        qty: [],
        route: [],
        status: [],
        stage: [],
        dimensions: [],
      }}
      bulkSelection={{
        selectedIds: new Set<number>(),
        selectedCount: 0,
        isSelected: () => false,
        isAllSelected: () => false,
        isIndeterminate: () => false,
        pruneTo: () => undefined,
        clear: vi.fn(),
        selectAllFiltered: () => undefined,
        selectOne: () => undefined,
      }}
      bulkProgress={null}
      bulkSummary={null}
      selectedBulkActionId="take-to-work"
      onActionChange={vi.fn()}
      executionBulkActions={[]}
      onRunSelectedBulkAction={vi.fn()}
      onEnterBulkMode={vi.fn()}
      onExitBulkMode={vi.fn()}
      sectionMetaById={new Map()}
      rowById={new Map()}
      onOpenDetail={vi.fn()}
      onSingleLaunch={vi.fn()}
      onManualPass={vi.fn()}
      onCancel={vi.fn()}
      onRestore={vi.fn()}
      onSoftDelete={vi.fn()}
      onToggleSelect={vi.fn()}
      onSelectAll={vi.fn()}
      onResetAll={vi.fn()}
      onRequestBulkSoftDelete={vi.fn()}
      onSkuClick={vi.fn()}
      tableScrollRef={createRef<HTMLDivElement>() as React.MutableRefObject<HTMLDivElement | null>}
      page={1}
      totalPages={1}
      total={0}
      limit={50}
      onPageChange={vi.fn()}
      onLimitChange={vi.fn()}
      rangeLabel=""
    />
  );
}

function headerCell(label: string): HTMLElement {
  const cell = screen
    .getAllByRole("columnheader")
    .find((candidate) => candidate.textContent?.startsWith(label));
  if (!cell) throw new Error(`Не найдена ячейка шапки «${label}»`);
  return cell;
}

describe("ExecutionTable: сортируемые колонки", () => {
  // Явный список: сверка с возможностями API, а не с текущим конфигом колонок.
  const SORTABLE_LABELS = ["№ / План", "Артикул", "Кол-во", "Размер", "Статус", "Этап"];
  const UNSORTABLE_LABELS = ["ID", "Наименование", "Маршрут"];

  it("не рисует кнопку сортировки у колонок, которые сервер не сортирует", () => {
    render(<Harness sortConfigs={[]} />);

    for (const label of UNSORTABLE_LABELS) {
      expect(
        within(headerCell(label)).queryByRole("button", { name: /Сортировка по/ }),
        `у колонки «${label}» не должно быть кнопки сортировки`,
      ).toBeNull();
    }
  });

  it("рисует кнопку сортировки ровно у серверно-сортируемых колонок", () => {
    render(<Harness sortConfigs={[]} />);

    const withSortButton = getExecutionTableColumns()
      .filter((column) => within(headerCell(column.label)).queryByRole("button", { name: /Сортировка по/ }))
      .map((column) => column.label);

    expect(withSortButton).toEqual(SORTABLE_LABELS);
  });

  it("не показывает состояние сортировки у несортируемой колонки, даже если оно есть в конфиге", () => {
    render(<Harness sortConfigs={[{ field: "route", order: "desc" }]} />);

    const cell = headerCell("Маршрут");
    expect(within(cell).queryByRole("button", { name: /Сортировка по/ })).toBeNull();
    expect(cell.getAttribute("aria-sort")).toBeNull();
  });

  it("показывает выбранное направление сортировки в сортируемой колонке", () => {
    render(<Harness sortConfigs={[{ field: "sku", order: "asc" }]} />);

    const cell = headerCell("Артикул");
    const sortButton = within(cell).getByRole("button", { name: /Сортировка по sku \(asc\)/ });
    expect(sortButton.getAttribute("data-sort-order")).toBe("asc");
    expect(cell.getAttribute("aria-sort")).toBe("ascending");
  });
});

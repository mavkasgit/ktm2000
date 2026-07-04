export type ImportRawSegment = {
  rowNumber: string;
  values: string[];
  variant: "source" | "duplicate";
  prefixLabel?: string;
};

type RawRowEntry = { rowNumber: string; data: Record<string, string> };

function buildRawRowsFromColumns(
  columnsByRow: Record<string, Record<string, string>> | undefined,
  singleColumns: Record<string, string> | undefined,
  singleRawRow: Record<string, string> | undefined,
  fallbackRowNum: string,
): RawRowEntry[] {
  if (columnsByRow && Object.keys(columnsByRow).length > 0) {
    return Object.entries(columnsByRow)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([num, data]) => ({ rowNumber: num, data }));
  }
  if (singleColumns && Object.keys(singleColumns).length > 0) {
    return [{ rowNumber: fallbackRowNum, data: singleColumns }];
  }
  if (singleRawRow) {
    return [{ rowNumber: fallbackRowNum, data: singleRawRow }];
  }
  return [];
}

function reorderColumns(data: Record<string, string>, order: string[]): Record<string, string> {
  if (order.length === 0) return data;
  const result: Record<string, string> = {};
  for (const key of order) {
    if (key in data) result[key] = data[key];
  }
  for (const key of Object.keys(data)) {
    if (!(key in result)) result[key] = data[key];
  }
  return result;
}

function toValues(data: Record<string, string>): string[] {
  return Object.values(data).filter(Boolean);
}

export function extractPlanImportRawRows(row: Record<string, unknown>): {
  segments: ImportRawSegment[];
  hasRawData: boolean;
} {
  const afterData = (row.after_data as Record<string, unknown> | undefined) ?? {};
  const payload = (row.payload as Record<string, unknown> | undefined) ?? {};

  const rawRow = payload.raw_excel_row as Record<string, string> | undefined;
  const rawColumns = payload.raw_columns as Record<string, string> | undefined;
  const rawColumnsByRow = payload.raw_columns_by_row as Record<string, Record<string, string>> | undefined;

  const allRawRows = buildRawRowsFromColumns(
    rawColumnsByRow,
    rawColumns,
    rawRow,
    String(row.source_row_number ?? ""),
  );

  const sourcePayload = (afterData.source_payload as Record<string, unknown> | undefined) ?? {};
  const serverRawColumns = sourcePayload.raw_columns as Record<string, string> | undefined;
  const serverRawColumnsByRow = sourcePayload.raw_columns_by_row as
    | Record<string, Record<string, string>>
    | undefined;
  const serverRawRow = sourcePayload.raw_excel_row as Record<string, string> | undefined;
  const serverRawRows = buildRawRowsFromColumns(
    serverRawColumnsByRow,
    serverRawColumns,
    serverRawRow,
    String((sourcePayload.row_numbers as number[] | undefined)?.[0] ?? row.source_row_number ?? ""),
  );

  const dupExistingPayload = (afterData.duplicate_existing_payload as Record<string, unknown> | undefined) ?? {};
  const dupExistingRawColumns = dupExistingPayload.raw_columns as Record<string, string> | undefined;
  const dupExistingRawColumnsByRow = dupExistingPayload.raw_columns_by_row as
    | Record<string, Record<string, string>>
    | undefined;
  const dupExistingRawRow = dupExistingPayload.raw_excel_row as Record<string, string> | undefined;
  const dupExistingRawRowsUnordered = buildRawRowsFromColumns(
    dupExistingRawColumnsByRow,
    dupExistingRawColumns,
    dupExistingRawRow,
    String(
      (dupExistingPayload.row_numbers as number[] | undefined)?.[0] ??
        afterData.duplicate_existing_row ??
        "",
    ),
  );

  const effectiveRawRows = allRawRows.length > 0 ? allRawRows : serverRawRows;
  const refColumnOrder =
    effectiveRawRows.length > 0
      ? Object.keys(effectiveRawRows[0].data)
      : serverRawRows.length > 0
        ? Object.keys(serverRawRows[0].data)
        : [];

  const dupExistingRawRows = dupExistingRawRowsUnordered.map((r) => ({
    ...r,
    data: reorderColumns(r.data, refColumnOrder),
  }));

  const planPosId = row.plan_position_id as number | undefined;
  const duplicateExistingId = afterData.duplicate_existing_id as number | undefined;

  let sourcePrefix = "";
  if (planPosId != null) sourcePrefix += `(#${planPosId}) `;
  if (duplicateExistingId != null) sourcePrefix += `(#${duplicateExistingId}) `;

  const segments: ImportRawSegment[] = [];

  for (const r of effectiveRawRows) {
    segments.push({
      rowNumber: r.rowNumber,
      values: toValues(r.data),
      variant: "source",
      prefixLabel: sourcePrefix || undefined,
    });
  }

  const dupId = afterData.duplicate_existing_id as number | undefined;
  for (const r of dupExistingRawRows) {
    segments.push({
      rowNumber: r.rowNumber,
      values: toValues(r.data),
      variant: "duplicate",
      prefixLabel: dupId ? `(#${dupId}) ` : undefined,
    });
  }

  return {
    segments,
    hasRawData: segments.length > 0,
  };
}
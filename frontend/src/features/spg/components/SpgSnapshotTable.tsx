import type {
  SpgSnapshotResponse,
  SpgSnapshotRow,
  SpgSnapshotPerSection,
} from "@/shared/api/spg";
import { Badge } from "@/shared/ui";

interface SpgSnapshotTableProps {
  snapshot: SpgSnapshotResponse;
  onShowProductRemainders?: (productId: number) => void;
}

function fmtNum(v: number): string {
  return v % 1 === 0 ? String(v) : v.toFixed(1);
}

function SectionCell({ data }: { data: SpgSnapshotPerSection | undefined }) {
  if (!data) return <td className="p-2 text-center text-muted-foreground">—</td>;
  const hasActivity =
    data.planned > 0 ||
    data.completed > 0 ||
    data.in_work > 0 ||
    data.remainder !== 0 ||
    data.issued !== 0;
  if (!hasActivity) return <td className="p-2 text-center text-muted-foreground">—</td>;

  return (
    <td className="p-2 text-center text-xs">
      {data.completed > 0 && (
        <div className="font-semibold text-emerald-700">{fmtNum(data.completed)}</div>
      )}
      {data.in_work > 0 && (
        <div className="text-blue-600">{fmtNum(data.in_work)} в работе</div>
      )}
      {data.available > 0 && (
        <div className="text-amber-600">{fmtNum(data.available)} дост.</div>
      )}
      {data.remainder !== 0 && (
        <div className={data.remainder < 0 ? "text-amber-600 font-medium" : "text-purple-600"}>
          {fmtNum(data.remainder)} ост.
        </div>
      )}
    </td>
  );
}

function MultiProgressBar({
  planned,
  available,
  issued,
  completionPct,
}: {
  planned: number;
  available: number;
  issued: number;
  completionPct: number;
}) {
  const total = Math.max(planned, available + issued);
  if (total <= 0) return <span className="text-xs text-muted-foreground">—</span>;

  const availablePct = Math.min(100, (available / total) * 100);
  const issuedPct = Math.min(100, (issued / total) * 100);
  const completedPct = Math.min(100, completionPct);

  return (
    <div className="flex flex-col gap-1 w-28">
      <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden flex">
        {/* Выполнено (зеленый) */}
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${completedPct}%` }}
          title={`Выполнено: ${completedPct}%`}
        />
        {/* Выдано в работу (оранжевый) */}
        <div
          className="h-full bg-amber-500 transition-all border-l border-background/20"
          style={{ width: `${issuedPct}%` }}
          title={`В работе: ${fmtNum(issued)} шт.`}
        />
        {/* Доступный задел (фиолетовый) */}
        <div
          className="h-full bg-purple-500 transition-all border-l border-background/20"
          style={{ width: `${availablePct}%` }}
          title={`Доступный задел: ${fmtNum(available)} шт.`}
        />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>План: {fmtNum(planned)}</span>
        <span>Факт: {completedPct}%</span>
      </div>
    </div>
  );
}

function DataRow({ row, sectionCodes, onShowRemainders }: { row: SpgSnapshotRow; sectionCodes: string[]; onShowRemainders?: (productId: number) => void }) {
  const clickable = !!onShowRemainders && (row.spg_available > 0 || row.issued_total > 0);
  const handleClick = () => {
    if (clickable && onShowRemainders) onShowRemainders(row.product_id);
  };
  return (
    <tr
      className={`border-b hover:bg-muted/30${row.negative_remainder_count > 0 ? " bg-red-50 hover:bg-red-100" : ""}`}
    >
      <td className="p-2">
        <div className="font-medium">{row.sku}</div>
        <div className="text-xs text-muted-foreground truncate max-w-[200px]">
          {row.product_name}
        </div>
      </td>
      <td className="p-2 text-right">
        {row.spg_available !== 0 ? (
          <button
            type="button"
            onClick={handleClick}
            disabled={!clickable}
            className={clickable ? "cursor-pointer hover:opacity-70" : "cursor-default"}
            title={clickable ? "Показать остатки и их историю" : undefined}
          >
            <Badge
              variant="secondary"
              className={row.spg_available < 0 ? "text-amber-700" : "text-purple-700"}
            >
              {fmtNum(row.spg_available)}
            </Badge>
          </button>
        ) : (
          <span className="text-muted-foreground text-xs">0</span>
        )}
      </td>
      <td className="p-2 text-right font-semibold">{fmtNum(row.planned_total)}</td>
      <td className="p-2 text-right text-emerald-700 font-medium">
        {row.completed_total !== 0 ? fmtNum(row.completed_total) : <span className="text-muted-foreground text-xs">0</span>}
      </td>
      <td className="p-2 text-right">
        {row.issued_total !== 0 ? (
          <button
            type="button"
            onClick={handleClick}
            disabled={!clickable}
            className={clickable ? "cursor-pointer hover:opacity-70" : "cursor-default"}
            title={clickable ? "Показать остатки и их историю" : undefined}
          >
            <Badge variant="secondary" className="text-amber-700">{fmtNum(row.issued_total)}</Badge>
          </button>
        ) : (
          <span className="text-muted-foreground text-xs">0</span>
        )}
      </td>
      {sectionCodes.map((code) => (
        <SectionCell key={code} data={row.per_section[code]} />
      ))}
      <td className="p-2">
        <MultiProgressBar
          planned={row.planned_total}
          available={row.spg_available}
          issued={row.issued_total}
          completionPct={row.completion_pct}
        />
      </td>
      <td className="p-2 text-center">
        {row.current_section && (
          <Badge variant="outline" className="text-xs">
            {row.current_section}
          </Badge>
        )}
      </td>
    </tr>
  );
}

export function SpgSnapshotTable({ snapshot, onShowProductRemainders }: SpgSnapshotTableProps) {
  const sectionCodes = snapshot.sections.map((s) => s.code);
  const { totals } = snapshot;
  const totalsPct = totals.planned > 0
    ? Math.round((totals.completed / totals.planned) * 100)
    : 0;

  if (snapshot.rows.length === 0) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        Нет данных по выбранным участкам
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 border-b">
          <tr>
            <th className="p-2 text-left font-medium sticky left-0 bg-muted/50">Артикул / Название</th>
            <th className="p-2 text-right font-medium text-purple-700">Доступно</th>
            <th className="p-2 text-right font-medium">План</th>
            <th className="p-2 text-right font-medium text-emerald-700">Выполнено</th>
            <th className="p-2 text-right font-medium text-amber-700">Выдано</th>
            {snapshot.sections.map((s) => (
              <th key={s.code} className="p-2 text-center font-medium text-xs whitespace-nowrap">
                {s.name}
              </th>
            ))}
            <th className="p-2 text-left font-medium">%</th>
            <th className="p-2 text-center font-medium">Где сейчас</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.rows.map((row) => (
            <DataRow
              key={row.product_id}
              row={row}
              sectionCodes={sectionCodes}
              onShowRemainders={onShowProductRemainders}
            />
          ))}
        </tbody>
        <tfoot className="bg-muted/30 border-t font-semibold">
          <tr>
            <td className="p-2 sticky left-0 bg-muted/30">Итого</td>
            <td className="p-2 text-right text-purple-700">
              {totals.spg_available !== 0 ? (
                <Badge
                  variant="secondary"
                  className={totals.spg_available < 0 ? "text-amber-700" : "text-purple-700"}
                >
                  {fmtNum(totals.spg_available)}
                </Badge>
              ) : (
                <span className="text-muted-foreground text-xs">0</span>
              )}
            </td>
            <td className="p-2 text-right">{fmtNum(totals.planned)}</td>
            <td className="p-2 text-right text-emerald-700">
              {totals.completed !== 0 ? fmtNum(totals.completed) : <span className="text-muted-foreground text-xs">0</span>}
            </td>
            <td className="p-2 text-right">
              {totals.issued !== 0 ? (
                <Badge variant="secondary" className="text-amber-700">{fmtNum(totals.issued)}</Badge>
              ) : (
                <span className="text-muted-foreground text-xs">0</span>
              )}
            </td>
            {sectionCodes.map((code) => {
              const sectionTotals = snapshot.rows.reduce(
                (acc, row) => {
                  const d = row.per_section[code];
                  if (d) {
                    acc.completed += d.completed;
                    acc.in_work += d.in_work;
                    acc.remainder += d.remainder;
                  }
                  return acc;
                },
                { completed: 0, in_work: 0, remainder: 0 },
              );
              return (
                <td key={code} className="p-2 text-center text-xs">
                  {sectionTotals.completed > 0 && (
                    <div className="text-emerald-700">{fmtNum(sectionTotals.completed)}</div>
                  )}
                  {sectionTotals.in_work > 0 && (
                    <div className="text-blue-600">{fmtNum(sectionTotals.in_work)}</div>
                  )}
                  {sectionTotals.remainder > 0 && (
                    <div className="text-purple-600">{fmtNum(sectionTotals.remainder)}</div>
                  )}
                  {sectionTotals.completed === 0 && sectionTotals.in_work === 0 && sectionTotals.remainder === 0 && "—"}
                </td>
              );
            })}
            <td className="p-2">
              <MultiProgressBar
                planned={totals.planned}
                available={totals.spg_available}
                issued={totals.issued}
                completionPct={totalsPct}
              />
            </td>
            <td className="p-2"></td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

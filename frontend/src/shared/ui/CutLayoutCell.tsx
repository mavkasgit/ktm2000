import type { CutLayout } from "@/shared/api/cutLayout";

export type CutLayoutCellProps = {
  /** Раскрой позиции; `null` — раскроя нет, показывается `fallback`. */
  layout?: CutLayout | null;
  /** Габарит задания для позиций без раскроя. */
  fallback?: string | null;
};

/**
 * Колонка «Размер»: вход со стрелкой слева (выровнен по центру колонки
 * распилов), распилы столбиком справа — каждый размер с новой строки.
 * Единый вид на странице плана, «Контроле выполнения» и доске участка.
 */
export function CutLayoutCell({ layout, fallback }: CutLayoutCellProps) {
  const input = layout?.input ?? null;
  const outputs = layout?.outputs ?? [];

  if (input === null && outputs.length === 0) {
    return <span>{fallback ?? "—"}</span>;
  }
  if (input === null) {
    return <CutLines outputs={outputs} />;
  }
  if (outputs.length === 0) {
    return <span>{input}</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 align-middle">
      <span className="shrink-0">{input} →</span>
      <CutLines outputs={outputs} />
    </span>
  );
}

function CutLines({ outputs }: { outputs: string[] }) {
  return (
    <span className="inline-flex flex-col">
      {outputs.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </span>
  );
}

/**
 * Сигнатура маршрута позиции (#214, ADR-0045): ожидаемая, фактическая и
 * вердикт «совпадает / расходится».
 *
 * Расхождение здесь только показывают: импорт, утверждение и выпуск
 * работают как раньде, отказ импорта — отдельная история (#215). Поэтому
 * карточка ничего не блокирует и молчит, когда сравнивать нечего.
 */
import { useQuery } from "@tanstack/react-query";

import { routeCheck } from "@/shared/api/productionPlans";
import type { RouteSignatureCheck, RouteSignatureStep } from "@/shared/api/productionPlans";
import { queryKeys } from "@/shared/api/queryKeys";

const VERDICT_LABEL: Record<RouteSignatureCheck["verdict"], string> = {
  match: "Сигнатуры совпадают",
  mismatch: "Сигнатуры расходятся",
  unknown: "Сигнатуры сравнить нельзя",
};

function stepText(step: RouteSignatureStep): string {
  const operations = step.operation_codes.filter(Boolean).join(", ");
  const flags = [
    step.is_significant ? "значимый" : null,
    step.transforms_dimensions ? "габариты" : null,
    step.is_final ? "финальный" : null,
  ].filter(Boolean);
  return [step.section_code, operations, flags.join(" · ")].filter(Boolean).join(" — ");
}

function SignatureColumn({
  title,
  signature,
  steps,
}: {
  title: string;
  signature: string | null;
  steps: RouteSignatureStep[];
}) {
  return (
    <div className="min-w-0 flex-1">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
        {title}
      </div>
      <code className="block break-all text-[11px] text-muted-foreground mb-1">
        {signature ?? "—"}
      </code>
      <ul className="space-y-0.5 text-sm">
        {steps.map((step, index) => (
          <li key={index} className="text-muted-foreground">
            {stepText(step)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RouteSignatureCheckCard({
  productionPlanId,
  positionId,
}: {
  productionPlanId: number;
  positionId: number;
}) {
  const { data } = useQuery({
    queryKey: queryKeys.plan.routeCheck(productionPlanId, positionId),
    queryFn: () => routeCheck(productionPlanId, positionId),
    staleTime: 60_000,
  });

  const signature = data?.route_signature;
  if (!signature || signature.verdict === "unknown") return null;

  const mismatch = signature.verdict === "mismatch";

  return (
    <div
      className={
        mismatch
          ? "rounded-lg border border-amber-300 bg-amber-50 p-3"
          : "rounded-lg border p-3"
      }
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold">Сигнатура маршрута</span>
        <span
          className={
            mismatch
              ? "text-xs font-semibold text-amber-800"
              : "text-xs font-semibold text-muted-foreground"
          }
        >
          {VERDICT_LABEL[signature.verdict]}
        </span>
      </div>
      <div className="flex flex-wrap gap-4">
        <SignatureColumn
          title="Ожидаемая (из входа сборки)"
          signature={signature.expected}
          steps={signature.expected_steps}
        />
        <SignatureColumn
          title="Фактическая (у маршрута)"
          signature={signature.actual}
          steps={signature.actual_steps}
        />
      </div>
    </div>
  );
}

/**
 * Маршрут позиции (#214, ADR-0045): одна строка с итоговым маршрутом и
 * вердикт «совпадает / расходится».
 *
 * Оператору показывается маршрут — участками и операциями по-русски, в
 * порядке прохождения. Коды участков, сырые строки сигнатур и признаки
 * этапа в интерфейс не выведены: это техника сверки, а не содержание
 * работы, а места в карточке под неё нет.
 *
 * Два маршрута целиком не печатаются. Когда они совпадают, второй столбец
 * читается как «тот же список дважды», и ноль сигнала на ровном маршруте.
 * Поэтому маршрут режется на общее начало, расхождение и общий конец: общее
 * печатается один раз, а на разрыве показываются оба ответа — что было
 * определено правилами импорта и что выбрано фактически.
 *
 * Расхождение здесь только показывают: импорт, утверждение и выпуск
 * работают как раньше, отказ импорта — отдельная история (#215). Карточка
 * ничего не блокирует и молчит, когда сравнивать нечего.
 */
import { useQuery } from "@tanstack/react-query";

import { routeCheck } from "@/shared/api/productionPlans";
import type { RouteSignatureCheck, RouteSignatureStep } from "@/shared/api/productionPlans";
import { queryKeys } from "@/shared/api/queryKeys";
import { cn } from "@/shared/utils/cn";

const VERDICT_LABEL: Record<RouteSignatureCheck["verdict"], string> = {
  match: "совпадает",
  mismatch: "расходится",
  unknown: "сравнить нельзя",
};

/** Подписи двух версий расхождения. Порядок важен: сверху «что должно было быть». */
const EXPECTED_LABEL = "Определено";
const ACTUAL_LABEL = "Выбрано";

/** Участок одним словом: название из справочника, иначе код. */
function sectionLabel(step: RouteSignatureStep): string {
  return step.section_name?.trim() || step.section_code;
}

/**
 * Операции этапа. Пустой код — транзитный склад, у него операций нет;
 * такие этапы в строке и не подписываются.
 */
function operationsOf(step: RouteSignatureStep): string[] {
  return step.operation_codes
    .map((code, index) => ({ code, name: step.operation_names?.[index] }))
    .filter((operation) => operation.code || operation.name)
    .map((operation) => operation.name?.trim() || operation.code);
}

const isTransit = (step: RouteSignatureStep) => step.stage_kind === "transit";

/**
 * Разбор двух маршрутов на «общее — расхождение — общее».
 *
 * Сравнение идёт по кодам участков: это единственное, что входит в
 * тождество маршрута (ADR-0045), переименование участка расхождения не
 * создаёт. Общее берётся с обоих концов — префикс и суффикс, — и всё, что
 * осталось между ними, и есть расхождение.
 */
function splitRoute(
  expected: RouteSignatureStep[],
  actual: RouteSignatureStep[],
): {
  expectedMiddle: RouteSignatureStep[];
  actualMiddle: RouteSignatureStep[];
} {
  let head = 0;
  while (
    head < expected.length &&
    head < actual.length &&
    expected[head].section_code === actual[head].section_code
  ) {
    head += 1;
  }

  let tail = 0;
  while (
    tail < expected.length - head &&
    tail < actual.length - head &&
    expected[expected.length - 1 - tail].section_code ===
      actual[actual.length - 1 - tail].section_code
  ) {
    tail += 1;
  }

  return {
    expectedMiddle: expected.slice(head, expected.length - tail),
    actualMiddle: actual.slice(head, actual.length - tail),
  };
}


function VerdictBadge({ verdict }: { verdict: RouteSignatureCheck["verdict"] }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[11px] font-medium",
        verdict === "match" && "bg-emerald-50 text-emerald-700",
        verdict === "mismatch" && "bg-amber-100 font-semibold text-amber-900",
        verdict === "unknown" && "text-muted-foreground",
      )}
    >
      {VERDICT_LABEL[verdict]}
    </span>
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
  const steps = signature.actual_steps;
  const lastIndex = steps.length - 1;
  const { expectedMiddle, actualMiddle } = splitRoute(
    signature.expected_steps,
    steps,
  );
  // Пустой блок означает, что совпало всё: расхождение нечего показывать.
  const divergedCodes = new Set(
    [...expectedMiddle, ...actualMiddle].map((step) => step.section_code),
  );
  const hasDivergence = mismatch && divergedCodes.size > 0;

  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        mismatch && "border-amber-300 bg-amber-50",
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold">Маршрут</span>
        <VerdictBadge verdict={signature.verdict} />
      </div>

      <ol className="flex items-stretch gap-0.5">
        {steps.map((step, index) => {
          const operations = operationsOf(step);
          const inDivergence = hasDivergence && divergedCodes.has(step.section_code);
          const wasExpected = inDivergence && expectedMiddle.some(
            (candidate) => candidate.section_code === step.section_code,
          );
          return (
            <li key={index} className="flex min-w-0 flex-1 flex-col">
              <div
                className={cn(
                  "h-1.5 rounded-sm",
                  isTransit(step) ? "bg-muted" : "bg-slate-700",
                  index === lastIndex && "bg-emerald-600",
                  inDivergence && (wasExpected ? "bg-amber-400" : "bg-amber-600"),
                )}
              />
              <div className="mt-1.5 flex items-baseline gap-1">
                <span className="text-[10px] tabular-nums text-muted-foreground">
                  {index + 1}
                </span>
                <span
                  className={cn(
                    "truncate text-xs font-medium",
                    isTransit(step) && "text-muted-foreground",
                    wasExpected && "text-amber-800/80 line-through",
                    inDivergence && !wasExpected && "text-amber-900",
                  )}
                  title={sectionLabel(step)}
                >
                  {inDivergence && !wasExpected ? "→ " : ""}
                  {sectionLabel(step)}
                </span>
              </div>
              {!isTransit(step) && operations.length > 0 && (
                <span
                  className="truncate text-[10px] text-muted-foreground"
                  title={operations.join(", ")}
                >
                  {operations.join(", ")}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {hasDivergence && (
        <div className="mt-2 space-y-1 rounded-md border border-amber-300 bg-amber-100/50 px-2 py-1.5 text-xs">
          <div className="flex items-baseline gap-2">
            <span className="w-24 shrink-0 text-[10px] uppercase tracking-wide text-amber-700/80">
              {EXPECTED_LABEL}
            </span>
            <span className="text-amber-900/90 line-through decoration-amber-500/60">
              {expectedMiddle.length > 0
                ? expectedMiddle.map(sectionLabel).join(" → ")
                : "этапа не было"}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="w-24 shrink-0 text-[10px] uppercase tracking-wide text-amber-900">
              {ACTUAL_LABEL}
            </span>
            <span className="font-semibold text-amber-950">
              {actualMiddle.length > 0
                ? actualMiddle.map(sectionLabel).join(" → ")
                : "этап пропущен"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * ProductRouteStageOut[] (секции с операциями) → плоские шаги для
 * RouteStepsDisplay (#153). Секция без операций (транзит) даёт один шаг
 * с именем секции вместо операции.
 */
import type { ProductRouteStageOut } from "@/shared/api/products";
import type { RouteStepsDisplayProps } from "@/shared/ui/RouteStepsDisplay";

export function stagesToSteps(stages: ProductRouteStageOut[]): RouteStepsDisplayProps["steps"] {
  return stages.flatMap((stage) => {
    const base = {
      sequence: stage.sequence,
      section_code: stage.section_code,
      section_name: stage.section_name,
      is_significant: stage.is_significant,
    };
    return stage.operations.length === 0
      ? [{ ...base, operation_code: null, operation_name: "" }]
      : stage.operations.map((op) => ({
          ...base,
          operation_code: op.operation_code,
          operation_name: op.operation_name,
        }));
  });
}

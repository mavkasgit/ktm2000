/**
 * Натуральная ширина ряда пилюль «Операций» (#483).
 *
 * Пилюли — не текст с переносом: одна строка, у каждой свой chrome. Поэтому
 * `pretext` им не нужен, а ширина собирается по фактическим классам
 * `RouteStepsDisplay` (`OperationStepPill`):
 *
 * - сам бейдж: `text-[10px] font-medium`, `px-1.5` (6+6), `gap-1` (4) до
 *   иконки, `border` (1+1), если у операции нет акцентного цвета;
 * - иконка `h-3 w-3` (12) или точка `size-2` (8);
 * - ряд: `flex gap-0.5` (2), разделители групп `›` (`px-0.5`) и `·`.
 *
 * Числа обязаны совпадать с компонентом: это единственное место, где они
 * записаны для модели. Если chrome пилюли меняется, меняется и он.
 */
import type { ImportOperationStep } from "@/shared/api/stock";

/** `text-[10px] font-medium` у подписи пилюли. */
export const PILL_LABEL_FONT_SIZE_PX = 10;
export const PILL_LABEL_FONT_WEIGHT = 500;
/** `leading-5` — высота пилюли, нужна только для полноты контракта. */
export const PILL_LINE_HEIGHT_PX = 20;

const PILL_PADDING_X_PX = 12; // px-1.5
const PILL_BORDER_PX = 2; // border, когда нет accentColor
const PILL_ICON_PX = 12; // h-3 w-3
const PILL_DOT_PX = 8; // size-2
const PILL_ICON_GAP_PX = 4; // gap-1
const PILL_ROW_GAP_PX = 2; // gap-0.5
const GROUP_SEPARATOR = "›";
const STEP_SEPARATOR = "·";
const GROUP_SEPARATOR_PADDING_PX = 4; // px-0.5 × 2

export type PillLabelMeasure = (text: string) => number;

type Step = ImportOperationStep;

function buildVisualLookup(referenceOps: readonly Step[]): Map<string, Step> {
  const map = new Map<string, Step>();
  for (const step of referenceOps) {
    if (step.operation_name) map.set(step.operation_name.trim().toLowerCase(), step);
    if (step.operation_code) map.set(step.operation_code.trim().toLowerCase(), step);
  }
  return map;
}

/** Копия `mergeStepVisuals`: иконка может прийти из справочника операций. */
function mergeStepVisuals(step: Step, lookup: Map<string, Step> | null): Step {
  if (!lookup) return step;
  const reference =
    lookup.get(step.operation_name.trim().toLowerCase()) ??
    (step.operation_code
      ? lookup.get(step.operation_code.trim().toLowerCase())
      : undefined);
  if (!reference) return step;
  return {
    ...step,
    section_icon: step.section_icon ?? reference.section_icon,
    section_icon_color: step.section_icon_color ?? reference.section_icon_color,
    op_icon: step.op_icon ?? reference.op_icon,
    op_icon_color: step.op_icon_color ?? reference.op_icon_color,
  };
}

/** Копия `groupStepsBySequence`: одинаковые `sequence` — одна группа. */
function groupBySequence(steps: readonly Step[]): Step[][] {
  const groups: Step[][] = [];
  const seen = new Set<number>();
  for (const step of steps) {
    if (seen.has(step.sequence)) continue;
    seen.add(step.sequence);
    groups.push(steps.filter((candidate) => candidate.sequence === step.sequence));
  }
  return groups;
}

function pillWidth(step: Step, measureLabel: PillLabelMeasure): number {
  const label = step.operation_name || step.section_name;
  const accentColor = step.op_icon_color ?? step.section_icon_color ?? null;
  const hasIcon = Boolean(
    (step.op_icon && step.op_icon_color) ||
      (step.section_icon && step.section_icon_color),
  );
  const hasDot =
    !hasIcon && Boolean(step.op_icon_color || step.section_icon_color);
  const icon = hasIcon ? PILL_ICON_PX : hasDot ? PILL_DOT_PX : 0;
  const border = accentColor ? 0 : PILL_BORDER_PX;
  return (
    PILL_PADDING_X_PX +
    border +
    (icon > 0 ? icon + PILL_ICON_GAP_PX : 0) +
    measureLabel(label)
  );
}

/**
 * Натуральная ширина ряда пилюль в одну строку (как `nowrap` в предпросмотре).
 * `0` — у строки нет этапов: ячейка печатает одну подпись, и она не задаёт
 * нижнюю границу колонки (обрезается так же, как раньше).
 */
export function pillRowNaturalWidth(
  steps: readonly Step[] | null | undefined,
  referenceOps: readonly Step[] | null | undefined,
  measureLabel: PillLabelMeasure,
): number {
  if (!steps || steps.length === 0) return 0;
  const lookup = referenceOps?.length ? buildVisualLookup(referenceOps) : null;
  const resolved = steps.map((step) => mergeStepVisuals(step, lookup));
  const groups = groupBySequence(resolved);

  let width = 0;
  let children = 0;
  groups.forEach((group, groupIndex) => {
    if (groupIndex > 0) {
      width += measureLabel(GROUP_SEPARATOR) + GROUP_SEPARATOR_PADDING_PX;
      children += 1;
    }
    group.forEach((step, stepIndex) => {
      if (stepIndex > 0) {
        width += measureLabel(STEP_SEPARATOR);
        children += 1;
      }
      width += pillWidth(step, measureLabel);
      children += 1;
    });
  });

  return width + Math.max(0, children - 1) * PILL_ROW_GAP_PX;
}

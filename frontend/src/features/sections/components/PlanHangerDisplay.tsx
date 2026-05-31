/**
 * components/PlanHangerDisplay.tsx
 * ================================
 * Компонент отображения количества подвесов для печатной формы плана.
 *
 * Используется только в специфических сценариях печати,
 * где нужно показать количество подвесов и штук на подвес.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Извлекает quantity_per_hanger из source_payload задачи.
 * Для парных профилей — из techcard_pair.inputs как '30+30'.
 * Для обычных — quantity_per_hanger.
 */
export function getQtyPerHanger(task: SectionBoardTask): number | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  // Paired profile: techcard_pair.inputs содержит techcard_quantity для каждого компонента
  const techcardPair = payload.techcard_pair as { inputs?: { techcard_quantity?: string }[] } | undefined;
  if (techcardPair?.inputs && techcardPair.inputs.length >= 2) {
    const qa = Number(techcardPair.inputs[0].techcard_quantity);
    const qb = Number(techcardPair.inputs[1].techcard_quantity);
    if (qa > 0 && qb > 0) {
      // Возвращаем первое значение для расчёта подвесов
      return qa;
    }
  }

  // Standard profile
  const val = payload.quantity_per_hanger;
  return typeof val === "number" ? val : null;
}

/** Для парных профилей возвращает строку '30+30', для обычных — null */
export function getPairedHangerLabel(task: SectionBoardTask): string | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  const techcardPair = payload.techcard_pair as { inputs?: { techcard_quantity?: string }[] } | undefined;
  if (techcardPair?.inputs && techcardPair.inputs.length >= 2) {
    const qa = Number(techcardPair.inputs[0].techcard_quantity);
    const qb = Number(techcardPair.inputs[1].techcard_quantity);
    if (qa > 0 && qb > 0) {
      return `${Math.round(qa)}+${Math.round(qb)}`;
    }
  }
  return null;
}

/** Считает количество подвесов по логике backend (hanger_quantity.py) */
export function adjustQtyToHanger(qty: number, qtyPerHanger: number | null) {
  if (!qtyPerHanger || qtyPerHanger <= 0 || qty <= 0) {
    return { hangers: 1 };
  }
  const hangers = Math.ceil(qty / qtyPerHanger);
  return { hangers };
}

// ---------------------------------------------------------------------------
// PlanHangerColumns — колонки подвесов для таблицы
// ---------------------------------------------------------------------------

interface PlanHangerColumnsProps {
  groupQty: number;
  task: SectionBoardTask;
}

/** Рендерит две ячейки таблицы: "Подвесов" и "Кол-во на подвес" */
export function PlanHangerColumns({ groupQty, task }: PlanHangerColumnsProps) {
  const qtyPerHanger = getQtyPerHanger(task);
  const pairedLabel = getPairedHangerLabel(task);
  const { hangers } = adjustQtyToHanger(groupQty, qtyPerHanger);

  return (
    <>
      <td className="px-1 py-0.5 text-left">{hangers}</td>
      <td className="px-1 py-0.5 text-left">{pairedLabel ?? (qtyPerHanger != null ? String(qtyPerHanger) : "—")}</td>
    </>
  );
}

/** Рендерит два заголовка для колонки подвесов */
export function PlanHangerHeaders() {
  return (
    <>
      <th className="text-left px-1 py-0.5 font-semibold whitespace-nowrap">Подвесов</th>
      <th className="text-left px-1 py-0.5 font-semibold" style={{ minWidth: "60px" }}>
        Кол-во<br />на подвес
      </th>
    </>
  );
}

/** Ренерит две пустые ячейки для строки "Итого" */
export function PlanHangerEmpty() {
  return (
    <>
      <td className="px-1 py-0.5 text-right"></td>
      <td className="px-1 py-0.5 text-right"></td>
    </>
  );
}

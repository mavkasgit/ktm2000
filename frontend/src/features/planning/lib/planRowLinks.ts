/**
 * Связи позиций плана — для колонки «Id» экрана «План».
 *
 * На экране рядом стоят позиции, которые оператор обязан читать вместе, а
 * импорт сделал отдельными. Такая связь одна — **пара**
 * (`payload.product_pair`, `resolved: true`): на подвесе едут два компонента,
 * норма подвеса у них одна, а печать сводит их в один подвес. Снимок —
 * решение импорта для конкретной позиции, поэтому вердикт «пара / не пара»
 * берём оттуда, а не строим заново по артикулам: одинокая строка артикула пары
 * помечена `reason: "no_paired_row"` и парой не является.
 *
 * Распила здесь нет намеренно. Одна заготовка, распиленная на несколько
 * длин, — это ОДНА позиция с несколькими выходами (ADR-0003, группа строк с
 * объединённой ячейкой входа): в плане она одна строка, выходы её видны в
 * колонке «Размер», а связывать нечего. Две отдельные позиции одного артикула
 * с одинаковым входом — это две самостоятельные операции пиле, и связывать их
 * было бы враньём оператору.
 *
 * Связи группируются по **видимым** строкам, а не по всему плану: сортировка и
 * фильтры меняют состав списка, и номер «2/2» должен значить «вторая из двух
 * видных», иначе подпись врёт.
 */

import type { PlanPositionOut } from "@/shared/api/productionPlans"

/** Снимок пары в `source_payload` — та форма, которую пишет импорт. */
type PairSnapshot = {
  pair_id?: unknown
  pair_name?: unknown
  quantity_per_hanger?: unknown
  resolved?: unknown
}

/** Связь позиции с парной позицией. */
export type PlanRowLink = {
  /** Подпись связи для подсказки: «Пара A+B · 30 шт на подвес». */
  title: string
  /** Место позиции среди связанных, с 1. */
  ordinal: number
  /** Сколько связанных позиций видно сейчас. */
  total: number
}

/**
 * Участник пары — только если импорт признал позицию её частью.
 *
 * `resolved: false` — это в том числе `no_paired_row` (одиночная строка) и
 * `product_pair_not_found` (пара в справочнике не заведена). Оба случая на
 * экране выглядят как отдельная позиция, и связывать её не с чем.
 */
function pairMemberOf(pos: PlanPositionOut): { id: number; groupKey: string; title: string } | null {
  const payload = pos.payload as { product_pair?: PairSnapshot } | null | undefined
  const pair = payload?.product_pair
  if (!pair || pair.resolved !== true) return null
  const pairId = typeof pair.pair_id === "number" ? pair.pair_id : null
  const pairName =
    typeof pair.pair_name === "string" && pair.pair_name.trim() ? pair.pair_name.trim() : null
  // Пара без номера и без имени — не пара, а разметка, которую читать нечем.
  if (pairId === null && pairName === null) return null
  const perHanger =
    typeof pair.quantity_per_hanger === "number" && pair.quantity_per_hanger > 0
      ? ` · ${pair.quantity_per_hanger} шт на подвес`
      : ""
  return {
    id: pos.id,
    // Ключ группы: пара из разных планов — это разные пары на экране.
    groupKey: `${pos.production_plan_id ?? "?"}:${pairId ?? pairName}`,
    title: `Пара ${pairName ?? `№${pairId}`}${perHanger}`,
  }
}

/**
 * Парные связи по видимым позициям: `id` позиции → её пара.
 *
 * Позиции вне пары в карте нет — ячейка «Id» у них остаётся как была. Группа
 * из одной позиции связи не даёт: связывать не с чем, и метка «1/1» вводила бы
 * в заблуждение.
 */
export function planRowLinks(rows: PlanPositionOut[]): Map<number, PlanRowLink> {
  const groups = new Map<string, { id: number; title: string }[]>()
  for (const pos of rows) {
    const member = pairMemberOf(pos)
    if (!member) continue
    const bucket = groups.get(member.groupKey)
    if (bucket) bucket.push({ id: member.id, title: member.title })
    else groups.set(member.groupKey, [{ id: member.id, title: member.title }])
  }

  const links = new Map<number, PlanRowLink>()
  for (const members of groups.values()) {
    if (members.length < 2) continue
    members.forEach((member, index) => {
      links.set(member.id, {
        title: member.title,
        ordinal: index + 1,
        total: members.length,
      })
    })
  }
  return links
}

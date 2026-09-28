/**
 * Кнопка действия с видимой причиной недоступности (#193).
 *
 * Причина, которая раньше жила только в `title` тултипа, показывается текстом
 * рядом с кнопкой: на сенсорном экране подсказки нет, и при первом открытии
 * страницы оператор её тоже не видит. Текст берётся из общего словаря
 * `actionReasons`, поэтому одна и та же причина звучит одинаково на доске, в
 * панели массовых операций и в передачах.
 *
 * Текст кладётся в ту же строку, что и кнопка: строка таблицы не растёт, иначе
 * виртуализация («одна высота на строку», ADR-0030) начинает считать неверно.
 * Длинный текст обрезается по месту, полный остаётся в `title`.
 *
 * Доступное действие (`reason = null`) не получает ни текста, ни обёртки: рядом
 * с работающей кнопкой лишних слов быть не должно.
 */
import type { ReactNode } from "react";

import { actionReasonText, type ActionReasonCode } from "@/shared/lib/actionReasons";
import { cn } from "@/shared/utils/cn";
/**
 * Текст не обрезается и не переносится: причина, которую нельзя прочитать,
 * хуже отсутствующей причины, а строка таблицы растёт от переноса — с ним
 * ломается расчёт высоты виртуализации (ADR-0030).
 */
const REASON_CLASS = "whitespace-nowrap text-[11px] leading-tight text-muted-foreground";

export type ActionWithReasonProps = {
  /** Код причины из `actionReasons`; `null` — действие доступно. */
  reason: ActionReasonCode | null;
  /** Кнопка или иной элемент действия. */
  children: ReactNode;
  /** Обёртка: по умолчанию строка, кнопка и текст в одну линию. */
  layout?: "row" | "column";
  className?: string;
};

export function ActionWithReason({
  reason,
  children,
  layout = "row",
  className,
}: ActionWithReasonProps) {
  const text = actionReasonText(reason);
  if (!text) return <>{children}</>;
  return (
    <div
      className={cn(
        "flex min-w-0 gap-1.5",
        layout === "row" ? "flex-row items-center justify-end" : "flex-col items-stretch",
        className,
      )}
    >
      {children}
      <span className={REASON_CLASS} title={text}>
        {text}
      </span>
    </div>
  );
}

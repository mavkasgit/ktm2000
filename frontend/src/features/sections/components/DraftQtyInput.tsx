/**
 * Ячейка-инпут массового ввода факта (#283).
 *
 * В режиме массовых операций «Годные» и «Брак» выделенной строки доски (и
 * шапки группы) становятся полем ввода. Поле обязано влезать в 32-пиксельную
 * строку — «одна высота на строку» держит виртуализацию (ADR-0030), поэтому
 * здесь компактный размер и никакого текста причины под полем: причину
 * отклонённого ввода оператор читает строкой футера, а не подсказкой под
 * курсором (ADR-0032, ADR-0049).
 *
 * Ввод нормализует `normalizeQuantityInput` — то же правило целых штук, что и
 * у полей факта в диалоге: своя регулярка рядом с полем разошлась бы с ним.
 *
 * Плейсхолдер — **сам записанный факт, без слова** («3», не «сейчас 3»):
 * полезная ширина поля 38px при 12px шрифте, и «сейчас 3» (47px) обрезалось уже
 * на однозначном числе, а «сейчас 1234» — на 66px. Смысл подписи несёт
 * подсказка `title` («Записано: 3»), а не место, которого нет.
 */

import { useState } from "react";
import { Input } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import { normalizeQuantityInput, type QuantityInputIssue } from "@/shared/lib/quantityInput";

export type DraftQtyInputProps = {
  value: string;
  onChange: (value: string) => void;
  /** Причина отклонённого ввода — футер показывает её текстом. */
  onIssue?: (issue: QuantityInputIssue | null) => void;
  /** Записанный факт (уже отформатированный): плейсхолдер и подсказка. */
  recorded: string;
  ariaLabel: string;
  /** Введённое больше доступного на задачу — помечается без наведения. */
  overPlan?: boolean;
  disabled?: boolean;
  className?: string;
};

export function DraftQtyInput({
  value,
  onChange,
  onIssue,
  recorded,
  ariaLabel,
  overPlan = false,
  disabled = false,
  className,
}: DraftQtyInputProps) {
  const [issue, setIssue] = useState<QuantityInputIssue | null>(null);

  const handleChange = (raw: string) => {
    const result = normalizeQuantityInput(raw);
    setIssue(result.issue);
    onIssue?.(result.issue);
    if (!result.issue) onChange(result.value);
  };

  return (
    <Input
      type="text"
      inputMode="numeric"
      value={value}
      onChange={(event) => handleChange(event.target.value)}
      onBlur={() => {
        setIssue(null);
        onIssue?.(null);
      }}
      // Клик и нажатия внутри поля не должны переключать выделение строки:
      // строка выбирается кликом, а поле — часть выделенной строки.
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") event.stopPropagation();
      }}
      placeholder={recorded}
      aria-label={ariaLabel}
      aria-invalid={issue !== null || overPlan}
      title={
        issue
          ? issue.text
          : overPlan
            ? "Сверх плана: больше доступного на задачу"
            : `Записано: ${recorded}`
      }
      disabled={disabled}
      className={cn(
        "h-7 w-16 text-xs",
        overPlan && "border-amber-500 bg-amber-50 text-amber-800",
        className,
      )}
    />
  );
}

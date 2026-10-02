/**
 * Ячейка-инпут массового ввода факта (#283).
 *
 * В режиме массовых операций «Годные» и «Брак» выделенной строки доски (и
 * шапки группы) становятся полем ввода. Поле обязано влезать в 32-пиксельную
 * строку — «одна высота на строку» держит виртуализацию (ADR-0030), поэтому
 * текст причины под полем не помещается.
 *
 * Причина отклонённого ввода показывается **у самого поля** — подсказкой,
 * раскрытой без наведения, пока ввод не станет допустимым. Прежде её печатал
 * футер подтверждения, и до него не доходили: строка с ошибкой и текст причины
 * жили в разных концах экрана. Поле при этом получает красную рамку: без неё
 * подсказка появлялась бы «из ниоткуда».
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/shared/ui/tooltip";
import { cn } from "@/shared/utils/cn";
import { normalizeQuantityInput, type QuantityInputIssue } from "@/shared/lib/quantityInput";

export type DraftQtyInputProps = {
  value: string;
  onChange: (value: string) => void;
  /** Записанный факт (уже отформатированный): плейсхолдер и подсказка. */
  recorded: string;
  ariaLabel: string;
  /**
   * Причина домена (ввод синтаксически верен, но неприменим — например «факт
   * меньше записанного»). Показывается у поля так же, как причина набора:
   * значение остаётся в поле, иначе цифру не добрать посимвольно.
   */
  issueText?: string | null;
  /** Введённое больше доступного на задачу — помечается без наведения. */
  overPlan?: boolean;
  disabled?: boolean;
  className?: string;
};

export function DraftQtyInput({
  value,
  onChange,
  recorded,
  ariaLabel,
  issueText = null,
  overPlan = false,
  disabled = false,
  className,
}: DraftQtyInputProps) {
  const [inputIssue, setInputIssue] = useState<QuantityInputIssue | null>(null);
  // Причина набора старше причины домена: она про только что набранный символ.
  const shownIssue = inputIssue?.text ?? issueText;

  const handleChange = (raw: string) => {
    const result = normalizeQuantityInput(raw);
    setInputIssue(result.issue);
    if (!result.issue) onChange(result.value);
  };

  return (
    // Подсказка раскрыта, пока ввод недопустим (`open` управляется состоянием,
    // а не наведением): причина обязана читаться без наведения, а под полем в
    // 32-пиксельной строке для неё места нет.
    <TooltipProvider delayDuration={0}>
      <Tooltip open={shownIssue !== null}>
        <TooltipTrigger asChild>
          <Input
            type="text"
            inputMode="numeric"
            value={value}
            onChange={(event) => handleChange(event.target.value)}
            onBlur={() => setInputIssue(null)}
            // Клик и нажатия внутри поля не должны переключать выделение
            // строки: строка выбирается кликом, а поле — часть выделенной строки.
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") event.stopPropagation();
            }}
            placeholder={recorded}
            aria-label={ariaLabel}
            aria-invalid={shownIssue !== null || overPlan}
            title={
              shownIssue ??
              (overPlan
                ? "Сверх плана: больше доступного на задачу"
                : `Записано: ${recorded}`)
            }
            disabled={disabled}
            className={cn(
              "h-7 w-16 text-xs",
              shownIssue !== null && "border-red-500 text-red-700",
              overPlan && shownIssue === null && "border-amber-500 bg-amber-50 text-amber-800",
              className,
            )}
          />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[240px] text-xs">
          {shownIssue}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

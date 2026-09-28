import React from "react";
import type { HangerLengthLine } from "../lib/hangerCalcRows";

/**
 * Ячейка колонки, печатающей по подстроке на длину (ADR-0050).
 *
 * Высота подстроки — `h-8`, то есть высота инпута периметра/габарита: строки
 * подстрок должны совпадать по высоте между колонками, а ячейки артикула и
 * полей ввода не должны раздувать строку (иначе браузер распределяет их
 * высоту по подстрокам и между колонками появляются разные интервалы). Это
 * уточнение общего набора строки (ADR-0030), объявленное рядом с таблицей,
 * которой оно принадлежит.
 */
const LINE_CLASS = "flex h-8 items-center text-xs";

export function HangerLineCell({
  lines,
  render,
}: {
  lines: readonly HangerLengthLine[];
  render: (line: HangerLengthLine) => React.ReactNode;
}) {
  return (
    <td className="px-4 py-0 align-top">
      {lines.map((line, index) => (
        <div key={line.lengthMm ?? `без-длины-${index}`} className={LINE_CLASS}>
          {render(line)}
        </div>
      ))}
    </td>
  );
}

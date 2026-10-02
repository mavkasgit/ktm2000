/**
 * BulkActionBar.tsx — общая нижняя панель массового действия.
 *
 * Панель подтверждения массового ввода факта (#283, доска участка) и панель
 * групповой передачи (#193, передачи) рисовались одинаково дважды — вплоть до
 * строки классов. Разметка живёт здесь одна: полоса во всю ширину окна — только
 * фон, содержимое стянуто в центрированную группу с потолком ширины. Иначе на
 * широком мониторе итог упирался в левый край, поля — в правый, а между ними
 * оставалась пустая половина экрана.
 *
 * Слоты:
 * - `summary` — что и сколько сейчас уедет: заголовок, итог, предупреждения;
 * - `children` — поля формы (дата, смена, комментарий), у каждого своя подпись;
 * - `actions` — кнопки действия, последняя колонка.
 */
import type { ReactNode } from "react";

import { cn } from "@/shared/utils/cn";

export type BulkActionBarProps = {
  /** Заголовок и итог: что именно сейчас записывается. */
  summary: ReactNode;
  /** Поля формы панели: дата, смена, комментарий и прочее. */
  children: ReactNode;
  /** Кнопки действия — последняя колонка панели. */
  actions: ReactNode;
  /** Дополнительные классы полосы (например, свой `z-index`). */
  className?: string;
};

export function BulkActionBar({ summary, children, actions, className }: BulkActionBarProps) {
  return (
    <div
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 backdrop-blur shadow-[0_-4px_24px_rgba(0,0,0,0.08)]",
        className,
      )}
    >
      <div className="mx-auto w-full max-w-[1440px] px-4 py-3 sm:px-6">
        <div className="flex flex-col items-center gap-3 xl:flex-row xl:items-center xl:justify-center xl:gap-x-8">
          <div className="w-full min-w-0 space-y-1.5 xl:w-auto xl:max-w-[560px]">{summary}</div>

          <div className="flex flex-col items-center gap-3 lg:flex-row lg:flex-wrap lg:items-end xl:shrink-0">
            {children}

            {/* Кнопки — на уровне полей: невидимая подпись занимает ту же
                строку, что «Дата»/«Смена»/«Комментарий», а причина отказа
                уходит вправо от кнопки, а не под неё (иначе блок кнопок выше
                остальных и кнопка висит ниже поля). */}
            <div className="flex flex-col gap-1.5">
              <span aria-hidden className="invisible text-sm font-medium">
                Действие
              </span>
              {/* `min-h-10`, а не `h-10`: на узком экране кнопки переносятся
                  на вторую строку, а не вылезают за поля. */}
              <div className="flex min-h-10 flex-wrap items-center justify-center gap-2">
                {actions}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

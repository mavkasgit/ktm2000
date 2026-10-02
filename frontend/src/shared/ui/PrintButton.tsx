/**
 * PrintButton.tsx — кнопка печати, одна на все экраны.
 *
 * Место в тулбаре у неё одно и то же: ряд фильтров, сразу после поиска — так
 * «Печать плана» стоит на доске участка и «Печать списка» в передачах. Что
 * печатается, решает страница: в лист уходит тот же набор, что видит оператор.
 * Раньше кнопка жила в фиче участков (`PlanPrintButton`), и второй экран либо
 * выдумывал свою, либо оставался без печати.
 */
import { Printer } from "lucide-react";

import { Button } from "./button";

export type PrintButtonProps = {
  /** Подпись кнопки: «Печать плана», «Печать списка». */
  label: string;
  onClick: () => void;
  disabled?: boolean;
};

export function PrintButton({ label, onClick, disabled }: PrintButtonProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="gap-2 whitespace-nowrap"
      onClick={onClick}
      disabled={disabled}
    >
      <Printer className="h-4 w-4" />
      {label}
    </Button>
  );
}

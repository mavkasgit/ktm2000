import { Printer } from "lucide-react";
import { Button } from "@/shared/ui";

/**
 * Печать текущего отображения участка. Одна кнопка на вкладки «Задания» и
 * «План»: одинаковое место — правый край строки над доской, — одинаковый вид
 * и иконка. Что печатается, решает страница: в модальное окно уходит тот же
 * набор, что видит оператор.
 */
export function PlanPrintButton({ onClick }: { onClick: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onClick}>
      <Printer className="h-4 w-4" />
      Печать плана
    </Button>
  );
}

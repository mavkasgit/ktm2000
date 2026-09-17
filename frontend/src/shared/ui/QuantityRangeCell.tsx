import { fmtQty } from "@/shared/utils/fmtQty";
import { countHangers } from "@/shared/lib/hangerCount";

export type QuantityRangeCellProps = {
  /** Итоговое количество: сколько штук получится по длинам (после округления до подвесов). */
  quantity: number | string;
  /**
   * Сырьё позиции (штуки входа, ADR-0003): до пилы материал считается
   * полноразмерными заготовками сырьевой длины.
   */
  inputQuantity?: number | string | null;
  /** Количество из плана (Excel) — левое число, когда сырья у позиции нет. */
  originalQuantity?: number | string | null;
  /** Норма «количество на подвес», штук. */
  quantityPerHanger?: number | null;
};

/**
 * Ячейка «Кол-во»: «сырьё - итог (NП)», где сырьё уступает место плану из
 * Excel, если входа у позиции нет; совпадающие числа не дублируются.
 * Единый вид на странице плана, «Контроле выполнения» и в превью импорта.
 */
export function QuantityRangeCell({
  quantity,
  inputQuantity,
  originalQuantity,
  quantityPerHanger,
}: QuantityRangeCellProps) {
  const qtyStr = fmtQty(quantity);
  const inputStr = isBlank(inputQuantity) ? null : fmtQty(inputQuantity);
  const originalStr = isBlank(originalQuantity) ? null : fmtQty(originalQuantity);
  // Левая граница — сырьё, а без него план из Excel; равные числа не дублируются.
  const sourceStr = inputStr ?? originalStr;
  const showRange = sourceStr !== null && sourceStr !== qtyStr;
  const hangerCount = countHangers(quantity, quantityPerHanger);

  return (
    <span className="whitespace-nowrap">
      {showRange && (
        <>
          <span
            className="text-muted-foreground"
            title={inputStr ? "Сырьё: полноразмерные заготовки сырьевой длины" : "Количество из плана"}
          >
            {sourceStr}
          </span>
          <span className="mx-1 text-muted-foreground">-</span>
        </>
      )}
      <span
        className={originalStr !== null && originalStr !== qtyStr ? "font-medium text-amber-600" : "font-medium"}
        title="Итог по длинам (после пилы)"
      >
        {qtyStr}
        {hangerCount != null ? ` (${hangerCount}П)` : ""}
      </span>
    </span>
  );
}

function isBlank(value: number | string | null | undefined): value is null | undefined | "" {
  return value == null || value === "";
}

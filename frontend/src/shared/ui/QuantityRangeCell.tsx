import { fmtQty } from "@/shared/lib/quantityFormat";
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
 * Ячейка «Кол-во»: «сырьё (NП) - итог», где сырьё уступает место плану из
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
  // Подвесы нарезаются из полноразмерного сырья до резки, поэтому считаем их
  // от входа, а не от количества выходных кусков после разбиения.
  let hangerBaseQuantity = quantity;
  if (!isBlank(originalQuantity)) hangerBaseQuantity = originalQuantity;
  if (!isBlank(inputQuantity)) hangerBaseQuantity = inputQuantity;
  const hangerCount = countHangers(hangerBaseQuantity, quantityPerHanger);
  const hangerLabel = hangerCount != null ? ` (${hangerCount}П)` : "";

  // Округление на подвесы идёт вверх, поэтому итог больше сырья ровно тогда,
  // когда сырьё не помещается в целые подвесы. Это и есть единственный повод
  // выделить итог оранжевым — когда взяли лишний подвес. В остальных случаях
  // итог серый, как и сырьё: чёрным он читался как «сырьё на месте», а в
  // строке без диапазона это вообще единственное число, и оно выглядело
  // главнее соседних строк. Вес не используется — жирным число читалось как
  // другое количество.
  const roundingAdded = originalStr !== null && originalStr !== qtyStr;

  return (
    <span className="whitespace-nowrap">
      {showRange && (
        <>
          <span
            className="text-muted-foreground"
            title={inputStr ? "Сырьё: полноразмерные заготовки сырьевой длины" : "Количество из плана"}
          >
            {sourceStr}
            {hangerCount != null && (
              <span className="font-normal text-muted-foreground">{hangerLabel}</span>
            )}
          </span>
          <span className="mx-1 text-muted-foreground">-</span>
        </>
      )}
      <span
        className={roundingAdded ? "text-amber-600" : "text-muted-foreground"}
        title="Итог после округления на подвесы"
      >
        {qtyStr}
        {!showRange && hangerCount != null && (
          <span className="font-normal text-muted-foreground">{hangerLabel}</span>
        )}
      </span>
    </span>
  );
}

function isBlank(value: number | string | null | undefined): value is null | undefined | "" {
  return value == null || value === "";
}

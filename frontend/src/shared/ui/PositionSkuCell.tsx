import { fmtQty } from "@/shared/lib/quantityFormat";

export type PositionSkuCellProps = {
  /** Артикул позиции; он же ключ снимка продукта для диалога статистики. */
  sku: string;
  /**
   * «Доступно для позиции» (#207): свободно минус то, что занято ЧУЖИМИ
   * открытыми позициями. Позиция не вычитает сама себя.
   */
  availableQuantity?: number | null;
  /**
   * «Дефицит позиции» (#207): сколько не хватает до планового количества
   * позиции. `0`/null — дефицита нет.
   */
  deficitQuantity?: number | null;
  /**
   * Если передан — артикул рендерится как кликабельная кнопка, открывающая
   * сводную информацию (ProductWipStatsDialog).
   */
  onClick?: (sku: string) => void;
  title?: string;
};

/**
 * Ячейка «Артикул» с индикатором остатка.
 * Используется на страницах «Планирование» и «Контроль выполнения».
 *
 * Два числа, отвечающие на вопрос «хватит ли сырья этой позиции» (#207):
 *
 *   [КП-460] 1500        — есть 1500, хватает
 *   [КП-460] 492 −12     — есть 492, не хватает 12
 *   [КП-460] 0 −318      — сырья нет, не хватает 318
 *   [КП-460]             — данных о наличии нет, индикатор молчит
 *
 * «Свободно на складах» (#207) в строку больше не выводится: это свойство
 * склада, а не позиции, и рядом с количеством позиции число вроде 1500
 * читалось как «втрое больше», хотя к позиции отношения не имеет.
 */
export function PositionSkuCell({
  sku,
  availableQuantity,
  deficitQuantity,
  onClick,
  title,
}: PositionSkuCellProps) {
  const showQuantity = typeof availableQuantity === "number";
  const hasDeficit = typeof deficitQuantity === "number" && deficitQuantity > 0;

  const skuElement = onClick ? (
    <button
      type="button"
      className="font-mono text-left text-blue-700 hover:underline focus:outline-none shrink-0"
      onClick={(e) => {
        e.stopPropagation();
        onClick(sku);
      }}
      title={title ?? "Показать сводную информацию по артикулу"}
    >
      {sku}
    </button>
  ) : (
    <span className="font-mono shrink-0" title={title}>
      {sku}
    </span>
  );

  return (
    <div className="flex items-center gap-1.5 min-w-0">
      {skuElement}
      {showQuantity && (
        <>
          {/* Порядок «есть, потом не хватает»: второе число читается как
              продолжение первого, а не как ещё одно количество наравне. */}
          <span
            className="font-mono text-xs text-muted-foreground shrink-0"
            data-testid="position-sku-available"
            title={`Доступно для позиции ${sku}: ${fmtQty(availableQuantity as number)} шт.`}
          >
            {fmtQty(availableQuantity as number)}
          </span>
          {hasDeficit && (
            <span
              className="font-mono text-xs text-amber-600 shrink-0"
              data-testid="position-sku-deficit"
              title={`Не хватает ${fmtQty(deficitQuantity as number)} шт. до планового количества`}
            >
              −{fmtQty(deficitQuantity as number)}
            </span>
          )}
        </>
      )}
    </div>
  );
}

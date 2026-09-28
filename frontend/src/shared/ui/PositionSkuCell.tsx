import { fmtQty } from "@/shared/lib/quantityFormat";

export type PositionSkuCellProps = {
  sku: string;
  /**
   * «Свободно на складах» (#207): физический годный остаток артикула по
   * складам-хранилищам. Свойство склада — не зависит ни от какой позиции.
   * `null`/`undefined` — данных о наличии нет, индикатор не показывается.
   */
  freeStockQuantity?: number | null;
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
 * Три числа с тремя именами (#207, решение Q4) — раньше здесь было одно
 * число, и оно вычитало саму позицию из остатка:
 *
 *   [КП-460] · 1500              — доступно для позиции
 *   [КП-460] · 1500 / 1200 · −300 — свободно на складах, доступно, дефицит
 *   [КП-460] · 0                 — действительно ноль
 *   [КП-460]                     — данных о наличии нет, индикатор молчит
 *
 * Когда «свободно» и «доступно» совпадают, показывается одно число: два
 * одинаковых числа рядом ничего не добавляют, а различаются они ровно
 * тогда, когда чужую позицию это касается.
 */
export function PositionSkuCell({
  sku,
  freeStockQuantity,
  availableQuantity,
  deficitQuantity,
  onClick,
  title,
}: PositionSkuCellProps) {
  const showQuantity = typeof availableQuantity === "number";
  const showFreeStock =
    typeof freeStockQuantity === "number" && freeStockQuantity !== availableQuantity;
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
    <div
      className="flex items-center gap-1.5 min-w-0"
      title={indicatorTitle(sku, freeStockQuantity, availableQuantity, deficitQuantity)}
    >
      {skuElement}
      {showQuantity && (
        <>
          {showFreeStock && (
            <span
              className="font-mono text-xs text-muted-foreground shrink-0"
              data-testid="position-sku-free-stock"
            >
              / {fmtQty(freeStockQuantity as number)}
            </span>
          )}
          <span
            className="font-mono text-xs text-muted-foreground shrink-0"
            data-testid="position-sku-available"
          >
            · {fmtQty(availableQuantity as number)}
          </span>
          {hasDeficit && (
            <span
              className="font-mono text-xs text-amber-600 shrink-0"
              data-testid="position-sku-deficit"
            >
              · −{fmtQty(deficitQuantity as number)}
            </span>
          )}
        </>
      )}
    </div>
  );
}

/** Подсказка с обоими числами и дефицитом — одним блоком, а не «· 0». */
function indicatorTitle(
  sku: string,
  freeStockQuantity?: number | null,
  availableQuantity?: number | null,
  deficitQuantity?: number | null,
): string {
  if (typeof availableQuantity !== "number") {
    return `Нет данных о наличии ${sku}`;
  }
  const parts = [
    `Свободно на складах: ${
      typeof freeStockQuantity === "number" ? fmtQty(freeStockQuantity) : "—"
    }`,
    `Доступно для позиции: ${fmtQty(availableQuantity)}`,
  ];
  if (typeof deficitQuantity === "number" && deficitQuantity > 0) {
    parts.push(`Дефицит позиции: ${fmtQty(deficitQuantity)}`);
  }
  return parts.join(" · ");
}

import { fmtQty } from "@/shared/utils/fmtQty";

export type PositionSkuCellProps = {
  sku: string;
  /**
   * Доступное количество остатков ГХП. Если `null` или `undefined` —
   * индикатор не показывается (например, у позиции нет маршрута).
   * Число 0 — показывается как `· 0`.
   */
  availableQuantity?: number | null;
  /**
   * Если передан — артикул рендерится как кликабельная кнопка, открывающая
   * сводную информацию (ProductWipStatsDialog).
   */
  onClick?: (sku: string) => void;
  title?: string;
};

/**
 * Ячейка «Артикул» с индикатором доступных остатков ГХП.
 * Используется на страницах «Планирование» и «Контроль выполнения».
 *
 * Формат вывода:
 *   [КП-460] · 350     — есть остатки
 *   [КП-460] · 0       — ноль остатков (всё равно показывается)
 *   [КП-460]           — индикатор не показывается (нет данных о наличии)
 */
export function PositionSkuCell({
  sku,
  availableQuantity,
  onClick,
  title,
}: PositionSkuCellProps) {
  const showQuantity = typeof availableQuantity === "number";

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
        <span className="font-mono text-xs text-muted-foreground shrink-0">
          · {fmtQty(availableQuantity as number)}
        </span>
      )}
    </div>
  );
}

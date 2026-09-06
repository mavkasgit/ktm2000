/**
 * Метка состава ГП для витрин импорта/карточки (#154): «ЮП-100×2; ЮП-200×3».
 * Дробные количества показываются с точностью импорта (3 знака), хвостовые
 * нули срезаются: 2.500 → «2.5», 2 → «2».
 */
export function compositionLabel(
  items: { sku: string; quantity: number }[] | null | undefined,
): string | null {
  if (!items || items.length === 0) return null;
  return items
    .map(({ sku, quantity }) => {
      const rounded = Number(quantity.toFixed(3));
      return `${sku}×${rounded}`;
    })
    .join("; ");
}

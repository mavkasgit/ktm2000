/**
 * Формат количества состава ГП (#152): дробные значения с точностью импорта
 * (3 знака), хвостовые нули срезаются: 2.500 → «2.5», 2 → «2».
 */
export function formatQuantity(quantity: number): string {
  return String(Number(quantity.toFixed(3)));
}

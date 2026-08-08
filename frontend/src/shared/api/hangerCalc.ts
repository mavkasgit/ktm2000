import { apiClient } from "./client";

/** Константы подвеса (#62). Отдаются эндпоинтом, фронт их в TS не дублирует. */
export type HangerSettings = {
  area_limit_m2: number;
  rod_length_mm: number;
  gap_mm: number;
  rod_count: number;
};

export type HangerCalcItem = {
  perimeter_mm: number | null;
  mount_width_mm: number | null;
  length_mm: number | null;
};

export type HangerCalcResult = {
  by_area: number | null;
  by_size: number | null;
  total: number | null;
  limiter: "area" | "size" | null;
  area_m2: number | null;
  is_calculable: boolean;
};

export type HangerCalcResponse = {
  results: HangerCalcResult[];
  hanger: HangerSettings;
};

/**
 * Stateless batch-расчёт «количество на подвес» (#62, POST /api/hanger-calc).
 * Результаты приходят в порядке items. Single = batch из одного item.
 * Нерасчётные данные → is_calculable=false без исключений; невалидные
 * константы/кросс-поле → 422 (обрабатывается вызывающим).
 */
export async function calcHanger(
  items: HangerCalcItem[],
  hanger?: Partial<HangerSettings>,
): Promise<HangerCalcResponse> {
  const { data } = await apiClient.post<HangerCalcResponse>("/hanger-calc", {
    items,
    ...(hanger ? { hanger } : {}),
  });
  return data;
}

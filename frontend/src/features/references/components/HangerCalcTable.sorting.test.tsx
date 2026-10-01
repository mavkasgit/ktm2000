/**
 * Сортировка таблицы «Расчёт подвесов»: на сервер уходит только то,
 * что сервер сортировать умеет, и ни одна выбранная колонка не должна
 * «съедать» сортировку соседней.
 *
 * Регресс: сортировка собиралась из `sortConfigs[0]`, поэтому выбор
 * клиентской колонки «Итог» первым обнулял сортировку по артикулу —
 * бейдж приоритета «2» стоял, а порядок строк не менялся.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  listProductsPaginated: vi.fn(),
  listProductPairCatalog: vi.fn(),
}));

vi.mock("@/shared/api/hangerCalc", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/hangerCalc")>()),
  calcHanger: vi.fn(),
  calcPairedHanger: vi.fn(),
}));


import type { Product } from "@/shared/api/products";
import { listProductPairCatalog, listProductsPaginated } from "@/shared/api/products";
import { calcHanger, calcPairedHanger } from "@/shared/api/hangerCalc";
import { HangerCalcTable } from "./HangerCalcTable";

const COMPONENT: Product = {
  id: 1,
  sku: "RAW-2700",
  code: null,
  name: "Профиль",
  type: "component",
  unit: "шт",
  is_active: true,
  notes: null,
  profile_type: null,
  alloy: null,
  color: null,
  anod_type: null,
  weight_per_meter: null,
  perimeter_mm: 64.2,
  mount_width_mm: 19.35,
  quantity_per_hanger: { "2700": { auto: 50, manual: 40 } },
  hanger_mode: "manual",
  cross_section: null,
  photo_thumb: null,
  photo_full: null,
  source: null,
  is_catalog_item: false,
  is_paired_profile: false,
  dimension_state: "length",
  skip_shot_blast: false,
  aliases: [],
  lengths: [{ length_mm: 2700, raw_length_mm: null, is_primary: true }],
  processing_flags: [],
  is_laminated: false,
};

const SETTINGS = { area_limit_m2: 13, rod_length_mm: 1450, gap_mm: 20, rod_count: 2 };

const renderTable = () =>
  render(<HangerCalcTable readOnly onEdit={() => {}} />);

/**
 * Кнопка сортировки колонки. Доступное имя собирается из подписи колонки
 * (#204), поэтому тест адресует кнопку по машинному полю в `data-sort-field`.
 */
function sortButton(field: string): HTMLElement {
  const button = document.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
  if (!button) throw new Error(`Не найдена кнопка сортировки колонки «${field}»`);
  return button;
}

const clickSort = (field: string) => fireEvent.click(sortButton(field));

/** Параметры последнего запроса списка компонентов. */
const lastParams = () => {
  const calls = vi.mocked(listProductsPaginated).mock.calls;
  return calls[calls.length - 1]?.[0];
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listProductsPaginated).mockResolvedValue({ items: [COMPONENT], total: 1, limit: 2000, offset: 0 });
  vi.mocked(listProductPairCatalog).mockResolvedValue([]);
  vi.mocked(calcHanger).mockResolvedValue({ results: [], hanger: SETTINGS });
  vi.mocked(calcPairedHanger).mockResolvedValue({ results: [], hanger: SETTINGS });
});

describe("HangerCalcTable: серверная сортировка", () => {
  /** Ждёт отрисовки шапок и возвращает число запросов, сделанных к этому моменту. */
  const waitForTable = async () => {
    await waitFor(() => expect(sortButton("sku")).toBeTruthy());
    return vi.mocked(listProductsPaginated).mock.calls.length;
  };

  it("сортировка только по клиентской колонке «Итог» в запрос не попадает", async () => {
    renderTable();
    const before = await waitForTable();

    clickSort("total");
    await waitFor(() => expect(vi.mocked(listProductsPaginated).mock.calls.length).toBeGreaterThan(before));
    expect(lastParams()?.sort).toBeUndefined();
  });

  it("клиентская колонка «Итог» не вытесняет сортировку по артикулу", async () => {
    renderTable();
    let before = await waitForTable();

    clickSort("total");
    await waitFor(() => expect(vi.mocked(listProductsPaginated).mock.calls.length).toBeGreaterThan(before));
    expect(lastParams()?.sort).toBeUndefined();

    before = vi.mocked(listProductsPaginated).mock.calls.length;
    clickSort("sku");
    await waitFor(() => expect(vi.mocked(listProductsPaginated).mock.calls.length).toBeGreaterThan(before));
    expect(lastParams()?.sort).toBe("sku:desc");
  });
});

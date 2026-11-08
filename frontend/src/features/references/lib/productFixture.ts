import type { Product } from "@/shared/api/products";

/**
 * Общая фабрика товара для тестов справочника.
 *
 * База нейтральна (фото нет, длин нет); специфичные для кейса поля
 * передаются через `overrides`, чтобы каждый тест явно называл то, что ему
 * важно, и не держал копию полного объекта.
 */
export function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: 1,
    sku: "033",
    code: null,
    name: "Профиль 033",
    type: "finished_good",
    unit: "шт",
    is_active: true,
    notes: null,
    profile_type: null,
    alloy: null,
    color: null,
    anod_type: null,
    weight_per_meter: null,
    perimeter_mm: null,
    mount_width_mm: null,
    quantity_per_hanger: null,
    hanger_mode: "auto",
    cross_section: null,
    photo_thumb: null,
    photo_thumb_version: null,
    photo_full: null,
    photo_full_version: null,
    source: null,
    is_catalog_item: false,
    is_paired_profile: false,
    dimension_state: "length",
    skip_shot_blast: false,
    aliases: [],
    lengths: [],
    processing_flags: [],
    is_laminated: false,
    composition: [],
    ...overrides,
  };
}

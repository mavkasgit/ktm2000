import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Product } from "@/shared/api/products";
import { CatalogCard } from "./CatalogCard";

function makeProduct(overrides: Partial<Product> = {}): Product {
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
    photo_thumb: "products/033_thumb.jpg",
    photo_thumb_version: "thumb-1",
    photo_full: "products/033_full.jpg",
    photo_full_version: "full-1",
    source: null,
    is_catalog_item: false,
    is_paired_profile: false,
    dimension_state: "length",
    skip_shot_blast: false,
    aliases: [],
    lengths: [],
    processing_flags: [],
    is_laminated: false,
    ...overrides,
  };
}

describe("CatalogCard", () => {
  it("renders the thumb URL with its version so the cache busts on replacement", () => {
    const { container } = render(<CatalogCard product={makeProduct()} onClick={vi.fn()} />);

    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "/static/products/033_thumb.jpg?v=thumb-1",
    );
  });
});

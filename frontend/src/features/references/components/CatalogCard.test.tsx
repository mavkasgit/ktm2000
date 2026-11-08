import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { makeProduct } from "../lib/productFixture";
import { CatalogCard } from "./CatalogCard";

describe("CatalogCard", () => {
  it("renders the thumb URL with its version so the cache busts on replacement", () => {
    const product = makeProduct({
      sku: "033",
      name: "Профиль 033",
      photo_thumb: "products/033_thumb.jpg",
      photo_thumb_version: "thumb-1",
      photo_full: "products/033_full.jpg",
      photo_full_version: "full-1",
    });

    const { container } = render(<CatalogCard product={product} onClick={vi.fn()} />);

    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "/static/products/033_thumb.jpg?v=thumb-1",
    );
  });

  it("renders the placeholder without falling back to the full photo", () => {
    const product = makeProduct({
      photo_thumb: null,
      photo_thumb_version: null,
      photo_full: "products/033_full.jpg",
      photo_full_version: "full-1",
    });

    const { container } = render(<CatalogCard product={product} onClick={vi.fn()} />);

    expect(container.querySelector("img")).toBeNull();
  });
});

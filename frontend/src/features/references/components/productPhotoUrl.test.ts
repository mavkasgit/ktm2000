import { describe, expect, it } from "vitest";

import { productPhotoUrl } from "./productPhotoUrl";

describe("productPhotoUrl", () => {
  const product = {
    photo_thumb: "products/033_thumb.jpg",
    photo_thumb_version: "thumb-1",
    photo_full: "products/033_full.jpg",
    photo_full_version: "full-1",
  };

  it("takes the thumb path with the thumb version", () => {
    expect(productPhotoUrl(product, "thumb")).toBe("/static/products/033_thumb.jpg?v=thumb-1");
  });

  it("takes the full path with the full version", () => {
    expect(productPhotoUrl(product, "full")).toBe("/static/products/033_full.jpg?v=full-1");
  });

  it("falls back to the other photo and keeps that file's version", () => {
    expect(productPhotoUrl({ ...product, photo_thumb: null }, "thumb")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(productPhotoUrl({ ...product, photo_full: null }, "full")).toBe(
      "/static/products/033_thumb.jpg?v=thumb-1",
    );
  });

  it("returns null when neither photo exists or the product is empty", () => {
    expect(
      productPhotoUrl(
        { photo_thumb: null, photo_thumb_version: null, photo_full: null, photo_full_version: null },
        "full",
      ),
    ).toBeNull();
    expect(productPhotoUrl(null, "thumb")).toBeNull();
  });
});

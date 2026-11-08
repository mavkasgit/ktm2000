import { describe, expect, it } from "vitest";

import { getPhotoUrl, productPhotoUrl } from "./getPhotoUrl";

describe("getPhotoUrl", () => {
  it("returns null for an empty path", () => {
    expect(getPhotoUrl(null)).toBeNull();
    expect(getPhotoUrl("")).toBeNull();
  });

  it("builds a static URL from a storage-relative path", () => {
    expect(getPhotoUrl("products/033_full.jpg")).toBe("/static/products/033_full.jpg");
  });

  it("normalizes Windows separators and keeps absolute paths", () => {
    expect(getPhotoUrl("products\\033_full.jpg")).toBe("/static/products/033_full.jpg");
    expect(getPhotoUrl("/static/products/033_full.jpg")).toBe("/static/products/033_full.jpg");
  });

  it("returns external URLs untouched when no version is supplied", () => {
    expect(getPhotoUrl("https://cdn.example.com/033_full.jpg")).toBe(
      "https://cdn.example.com/033_full.jpg",
    );
  });

  it("appends an explicit version to an external URL", () => {
    expect(getPhotoUrl("https://cdn.example.com/033_full.jpg", "ext-1")).toBe(
      "https://cdn.example.com/033_full.jpg?v=ext-1",
    );
  });

  it("appends the per-photo version as a cache-busting query", () => {
    expect(getPhotoUrl("products/033_full.jpg", "1a2b-3c4d")).toBe(
      "/static/products/033_full.jpg?v=1a2b-3c4d",
    );
  });

  it("keeps the URL stable for the same version and changes it for another", () => {
    const first = getPhotoUrl("products/033_full.jpg", "same");
    const again = getPhotoUrl("products/033_full.jpg", "same");
    const changed = getPhotoUrl("products/033_full.jpg", "next");

    expect(first).toBe("/static/products/033_full.jpg?v=same");
    expect(again).toBe(first);
    expect(changed).not.toBe(first);
  });

  it("does not add a version when it is absent", () => {
    expect(getPhotoUrl("products/033_full.jpg", null)).toBe("/static/products/033_full.jpg");
  });

  it("uses & when the path already has a query string", () => {
    expect(getPhotoUrl("/static/products/033_full.jpg?download=1", "v1")).toBe(
      "/static/products/033_full.jpg?download=1&v=v1",
    );
  });
});

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

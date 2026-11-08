import { describe, expect, it } from "vitest";

import { getPhotoUrl } from "./getPhotoUrl";

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

  it("returns external URLs untouched", () => {
    expect(getPhotoUrl("https://cdn.example.com/033_full.jpg")).toBe(
      "https://cdn.example.com/033_full.jpg",
    );
  });

  it("never adds a version to an external URL", () => {
    expect(getPhotoUrl("https://cdn.example.com/033_full.jpg", "ext-1")).toBe(
      "https://cdn.example.com/033_full.jpg",
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

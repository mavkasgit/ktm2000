import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeProduct } from "../lib/productFixture";
import { ProductPhoto } from "./ProductPhoto";

describe("ProductPhoto", () => {
  it("uses the thumb version in the image URL", () => {
    const product = makeProduct({
      photo_thumb: "products/033_thumb.jpg",
      photo_thumb_version: "1a2b-3c4d",
      photo_full: "products/033_full.jpg",
      photo_full_version: "5e6f-7a8b",
    });

    const { container } = render(<ProductPhoto product={product} />);

    const image = container.querySelector("img");
    expect(image?.getAttribute("src")).toBe("/static/products/033_thumb.jpg?v=1a2b-3c4d");
  });

  it("renders the placeholder when the product has no thumb", () => {
    const product = makeProduct({
      photo_thumb: null,
      photo_thumb_version: null,
      photo_full: "products/033_full.jpg",
      photo_full_version: "5e6f-7a8b",
    });

    const { container } = render(<ProductPhoto product={product} />);

    expect(container.querySelector("img")).toBeNull();
  });
});

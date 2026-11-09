import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ImageUploadModal } from "./ImageUploadModal";

let nextBlob = 0;
let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;

function imageFile(name = "photo.png") {
  return new File(["bytes"], name, { type: "image/png" });
}

function selectFile(file: File) {
  // Dialog.Portal рендерит содержимое в document.body, а не в container.
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  nextBlob = 0;
  createObjectURL = vi.fn(() => `blob:${++nextBlob}`);
  revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectURL,
  });
});

afterEach(() => {
  cleanup();
});

describe("ImageUploadModal — blob-URL превью", () => {
  it("освобождает предыдущий URL при замене, удалении и размонтировании", () => {
    const { unmount } = render(
      <ImageUploadModal open onOpenChange={vi.fn()} onFileSelected={vi.fn()} />,
    );

    selectFile(imageFile("first.png"));
    expect(screen.getByAltText("Preview").getAttribute("src")).toBe("blob:1");

    selectFile(imageFile("second.png"));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:1");
    expect(screen.getByAltText("Preview").getAttribute("src")).toBe("blob:2");

    fireEvent.click(screen.getByRole("button", { name: "Удалить превью" }));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:2");
    expect(screen.queryByAltText("Preview")).toBeNull();

    selectFile(imageFile("third.png"));
    expect(screen.getByAltText("Preview").getAttribute("src")).toBe("blob:3");

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:3");
  });

  it("в StrictMode не отзывает URL, который ещё показывается", () => {
    const { unmount } = render(
      <StrictMode>
        <ImageUploadModal open onOpenChange={vi.fn()} onFileSelected={vi.fn()} />
      </StrictMode>,
    );

    selectFile(imageFile("strict.png"));

    expect(screen.getByAltText("Preview").getAttribute("src")).toBe("blob:1");
    expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:1");

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:1");
  });
});

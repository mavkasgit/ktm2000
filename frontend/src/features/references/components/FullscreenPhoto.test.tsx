import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FullscreenPhoto } from "./FullscreenPhoto";

describe("FullscreenPhoto", () => {
  beforeEach(() => {
    // happy-dom не умеет Fullscreen API: компонент не должен падать на его отсутствии.
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts fit-to-screen instead of 1:1", () => {
    const { container } = render(<FullscreenPhoto src="/photo.jpg" alt="Фото" onClose={() => {}} />);

    const image = container.querySelector("img");
    expect(image).not.toBeNull();
    expect(image?.className).toContain("max-h-full");
    expect(image?.className).toContain("max-w-full");
    expect(image?.className).toContain("object-contain");
    expect(image?.className).not.toContain("max-w-none");
    expect(image?.style.transform).toContain("scale(1)");
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<FullscreenPhoto src="/photo.jpg" alt="Фото" onClose={onClose} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("double-click resets zoom back to fit", () => {
    const { container } = render(<FullscreenPhoto src="/photo.jpg" alt="Фото" onClose={() => {}} />);
    const overlay = container.firstElementChild as HTMLElement;

    fireEvent.click(screen.getByTitle("Приблизить (+)"));
    expect(container.querySelector("img")?.style.transform).toMatch(/scale\(1\.5\)$/);

    fireEvent.doubleClick(overlay);
    expect(container.querySelector("img")?.style.transform).toMatch(/scale\(1\)$/);
  });
});

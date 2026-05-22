import { describe, expect, it } from "vitest";
import { isEditableTarget, isHotkeyInScope } from "./hotkeys";

describe("bulk hotkeys", () => {
  it("ignores editable targets", () => {
    expect(isEditableTarget({ tagName: "input" } as unknown as EventTarget)).toBe(true);
    expect(isEditableTarget({ tagName: "textarea" } as unknown as EventTarget)).toBe(true);
    expect(isEditableTarget({ tagName: "div" } as unknown as EventTarget)).toBe(false);
  });

  it("requires the keyboard event target to be inside the scoped table", () => {
    const child = {};
    const outside = {};
    const scope = {
      contains: (node: object) => node === child,
    } as unknown as HTMLElement;
    expect(isHotkeyInScope(scope, child as unknown as EventTarget)).toBe(true);
    expect(isHotkeyInScope(scope, outside as unknown as EventTarget)).toBe(false);
  });
});

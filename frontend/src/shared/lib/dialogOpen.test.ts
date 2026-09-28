import { describe, expect, it } from "vitest";

import { isAnyDialogOpen } from "./dialogOpen";

/** Разметка окна в том виде, который даёт общий каркас (Radix). */
const dialog = (state: string) => `<div role="dialog" data-state="${state}"></div>`;

describe("isAnyDialogOpen", () => {
  it("закрытая страница — окна нет", () => {
    const root = document.createElement("div");
    expect(isAnyDialogOpen(root)).toBe(false);
  });

  it("открытое окно каркаса распознаётся", () => {
    const root = document.createElement("div");
    root.innerHTML = dialog("open");
    expect(isAnyDialogOpen(root)).toBe(true);
  });

  it("закрытое окно в DOM не считается открытым", () => {
    const root = document.createElement("div");
    root.innerHTML = dialog("closed");
    expect(isAnyDialogOpen(root)).toBe(false);
  });

  it("окно без role не считается окном каркаса", () => {
    const root = document.createElement("div");
    root.innerHTML = '<div class="fixed inset-0" data-state="open"></div>';
    expect(isAnyDialogOpen(root)).toBe(false);
  });

  it("одно открытое окно среди закрытых даёт true", () => {
    const root = document.createElement("div");
    root.innerHTML = `${dialog("closed")}${dialog("open")}${dialog("closed")}`;
    expect(isAnyDialogOpen(root)).toBe(true);
  });
});

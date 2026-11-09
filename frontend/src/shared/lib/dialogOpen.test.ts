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

  it("AlertDialog — тоже модальное окно", () => {
    const root = document.createElement("div");
    root.innerHTML = '<div role="alertdialog" data-state="open"></div>';
    expect(isAnyDialogOpen(root)).toBe(true);
  });

  it("меню и Select забирают Escape, пока открыты", () => {
    for (const role of ["menu", "listbox"]) {
      const root = document.createElement("div");
      root.innerHTML = `<div role="${role}" data-state="open"></div>`;
      expect(isAnyDialogOpen(root), role).toBe(true);
    }
  });

  it("Popover в портале Radix тоже считается открытым слоем", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<div data-radix-popper-content-wrapper><div data-state="open"></div></div>';
    expect(isAnyDialogOpen(root)).toBe(true);
  });

  it("закрытое меню не мешает странице обработать Escape", () => {
    const root = document.createElement("div");
    root.innerHTML = '<div role="menu" data-state="closed"></div>';
    expect(isAnyDialogOpen(root)).toBe(false);
  });

  it("одно открытое окно среди закрытых даёт true", () => {
    const root = document.createElement("div");
    root.innerHTML = `${dialog("closed")}${dialog("open")}${dialog("closed")}`;
    expect(isAnyDialogOpen(root)).toBe(true);
  });
});

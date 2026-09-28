import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { isChunkLoadError, RouteErrorScreen } from "./routeError";

describe("RouteErrorScreen", () => {
  it("объясняет, что приложение обновилось, и предлагает обновить страницу", () => {
    render(<RouteErrorScreen reason="chunk" onReload={() => {}} />);

    expect(screen.getByRole("heading", { name: "Не удалось загрузить раздел" })).toBeTruthy();
    expect(screen.getByText(/вкладка осталась со старой версией/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Обновить страницу/ })).toBeTruthy();
  });

  it("кнопка «Обновить страницу» перезагружает страницу", () => {
    const onReload = vi.fn();
    render(<RouteErrorScreen reason="chunk" onReload={onReload} />);

    fireEvent.click(screen.getByRole("button", { name: /Обновить страницу/ }));

    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("при ошибке самого раздела не советует обновление как лечение", () => {
    render(<RouteErrorScreen reason="unknown" onReload={() => {}} />);

    expect(screen.queryByText(/вкладка осталась со старой версией/i)).toBeNull();
    expect(screen.getByText(/не открылась из-за ошибки/i)).toBeTruthy();
  });
});

describe("isChunkLoadError", () => {
  it("узнаёт сообщения браузеров о неудачной загрузке модуля", () => {
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module"))).toBe(true);
    expect(isChunkLoadError(new Error("error loading dynamically imported module"))).toBe(true);
    expect(isChunkLoadError(new Error("Importing a module script failed"))).toBe(true);
  });

  it("ошибку самого раздела загрузкой чанка не считает", () => {
    expect(isChunkLoadError(new Error("Неизвестно"))).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });
});

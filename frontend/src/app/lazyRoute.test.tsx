import { Component, type ErrorInfo, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RouteBoundary, lazyPage } from "./lazyRoute";

/** Промис под нашим контролем: чанк «едет», пока тест сам его не отпустит. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

class ErrorCatcher extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Подробности React сам выведет в консоль; тесту нужен сам факт ошибки.
  }

  render() {
    if (this.state.error) {
      return <div data-testid="route-error">{this.state.error.message}</div>;
    }
    return this.props.children;
  }
}

// React 18 логирует ошибку, пойманную границей, в console.error — это шум
// кейса про ошибку, а не его сигнал. Подменяем только там и восстанавливаем.
afterEach(() => {
  vi.restoreAllMocks();
});

describe("RouteBoundary + lazyPage", () => {
  it("на месте неразрешённого чанка — спиннер, после резолва — страница из модуля", async () => {
    const chunk = deferred<{ SectionPage: () => ReactNode }>();
    const Page = lazyPage(() => chunk.promise, "SectionPage");

    render(
      <RouteBoundary>
        <Page />
      </RouteBoundary>,
    );

    // Пока чанк едет: виден явный индикатор загрузки, а не пустое место.
    const pending = screen.getByTestId("route-pending");
    expect(pending.getAttribute("role")).toBe("status");
    expect(pending.getAttribute("aria-label")).toBe("Загрузка раздела");
    expect(screen.queryByTestId("section-page")).toBeNull();

    chunk.resolve({
      SectionPage: () => <div data-testid="section-page">Страница раздела</div>,
    });

    await screen.findByTestId("section-page");
    expect(screen.getByTestId("section-page").textContent).toBe("Страница раздела");
    expect(screen.queryByTestId("route-pending")).toBeNull();
  });

  it("берёт компонент по имени экспорта, а не default модуля", async () => {
    const Page = lazyPage(
      () =>
        Promise.resolve({
          default: () => <div data-testid="wrong-page">default модуля</div>,
          SectionPage: () => <div data-testid="section-page">именованный экспорт</div>,
        }),
      "SectionPage",
    );

    render(
      <RouteBoundary>
        <Page />
      </RouteBoundary>,
    );

    await screen.findByTestId("section-page");
    expect(screen.getByTestId("section-page").textContent).toBe("именованный экспорт");
    expect(screen.queryByTestId("wrong-page")).toBeNull();
  });

  it("отсутствующий экспорт: ошибка с именем экспорта вместо молчаливого пустого раздела", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    // Роутер запрашивает имя, которого в модуле уже нет (экспорт переименовали,
    // чанк отстал) — ровно тот случай, ради которого lazyPage проверяет наличие.
    const renamedModule = { OtherPage: () => <div data-testid="other-page" /> };
    const Page = lazyPage<Record<string, unknown>, string>(
      () => Promise.resolve(renamedModule),
      "SectionPage",
    );

    render(
      <ErrorCatcher>
        <RouteBoundary>
          <Page />
        </RouteBoundary>
      </ErrorCatcher>,
    );

    const message = (await screen.findByTestId("route-error")).textContent ?? "";
    expect(message).toContain("SectionPage");
    // Спиннер — это состояние «ещё грузим», а не «не нашлось»: ушедший в ошибку
    // маршрут не должен навсегда замереть в индикаторе загрузки.
    expect(screen.queryByTestId("route-pending")).toBeNull();
    expect(screen.queryByTestId("other-page")).toBeNull();
  });
});

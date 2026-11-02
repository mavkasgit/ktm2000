// @vitest-environment happy-dom

import { describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { DRAG_THRESHOLD_PX, MobileScrollTable, stickyCell, useTableSwipe } from "./MobileScrollTable";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Примитив мобильной таблицы (#343): закреплённые колонки и свайп по всей
 * поверхности. Проверяется то, ради чего он существует, — жест мышью двигает
 * таблицу, короткий сдвиг остаётся нажатием, а поля ввода и кнопки не
 * перехватываются.
 *
 * Контейнер подменён простым объектом с `scrollLeft`/`scrollWidth`: в happy-dom
 * раскладки нет, размеры нулевые, и «есть ли что тащить» на живом узле не
 * проверить. Сами обработчики — публичный интерфейс хука, поэтому тест идёт
 * через них, а не через внутренние поля.
 */

interface FakeContainer {
  scrollLeft: number;
  clientWidth: number;
  scrollWidth: number;
  setPointerCapture: ReturnType<typeof vi.fn>;
  releasePointerCapture: ReturnType<typeof vi.fn>;
  hasPointerCapture: () => boolean;
}

function makeContainer(overrides: Partial<FakeContainer> = {}): FakeContainer {
  return {
    scrollLeft: 0,
    clientWidth: 300,
    scrollWidth: 900,
    setPointerCapture: vi.fn(),
    releasePointerCapture: vi.fn(),
    hasPointerCapture: () => true,
    ...overrides,
  };
}

interface PointerOverrides {
  pointerType?: string;
  target?: EventTarget;
  clientX?: number;
  clientY?: number;
  button?: number;
  pointerId?: number;
}

function pointerEvent(
  container: FakeContainer,
  { pointerType = "mouse", target = document.createElement("td"), clientX = 200, clientY = 10, button = 0, pointerId = 1 }: PointerOverrides = {},
) {
  return {
    currentTarget: container as unknown as HTMLElement,
    target,
    pointerId,
    pointerType,
    button,
    clientX,
    clientY,
    preventDefault: vi.fn(),
  } as unknown as React.PointerEvent<HTMLElement>;
}

function mountSwipe(options?: { thresholdPx?: number }) {
  const container = document.createElement("div");
  const root: Root = createRoot(container);
  const state: { current: ReturnType<typeof useTableSwipe> | null } = { current: null };

  function Harness() {
    state.current = useTableSwipe(options);
    return null;
  }

  act(() => {
    root.render(<Harness />);
  });

  return {
    get swipe() {
      if (!state.current) throw new Error("хук не смонтирован");
      return state.current;
    },
    unmount: () => act(() => root.unmount()),
  };
}

/** Полный жест: нажали, провели, отпустили. Возвращает событие клика после него. */
function drag(
  swipe: ReturnType<typeof useTableSwipe>,
  container: FakeContainer,
  { from = 200, to = 100, overrides = {} as PointerOverrides } = {},
) {
  act(() => swipe.handlers.onPointerDown(pointerEvent(container, { clientX: from, ...overrides })));
  act(() => swipe.handlers.onPointerMove(pointerEvent(container, { clientX: to, ...overrides })));
  act(() => swipe.handlers.onPointerUp(pointerEvent(container, { clientX: to, ...overrides })));
}

describe("useTableSwipe", () => {
  it("перетаскивание мышью двигает таблицу после порога", () => {
    const mounted = mountSwipe();
    const container = makeContainer();

    drag(mounted.swipe, container, { from: 200, to: 100 });

    // Палец ушёл влево на 100 — содержимое уехало вправо на те же 100.
    expect(container.scrollLeft).toBe(100);
    expect(mounted.swipe.isDragging).toBe(false);
    mounted.unmount();
  });

  it("сдвиг меньше порога остаётся нажатием: таблица стоит, клик не глушится", () => {
    const mounted = mountSwipe();
    const container = makeContainer();
    const click = { preventDefault: vi.fn(), stopPropagation: vi.fn() };

    drag(mounted.swipe, container, { from: 200, to: 200 - (DRAG_THRESHOLD_PX - 1) });
    act(() => mounted.swipe.handlers.onClickCapture(click as unknown as React.MouseEvent<HTMLElement>));

    expect(container.scrollLeft).toBe(0);
    expect(click.preventDefault).not.toHaveBeenCalled();
    expect(click.stopPropagation).not.toHaveBeenCalled();
    mounted.unmount();
  });

  it("после настоящего перетаскивания синтетический клик не доходит до строки", () => {
    const mounted = mountSwipe();
    const container = makeContainer();
    const afterDrag = { preventDefault: vi.fn(), stopPropagation: vi.fn() };

    drag(mounted.swipe, container, { from: 200, to: 100 });
    act(() => mounted.swipe.handlers.onClickCapture(afterDrag as unknown as React.MouseEvent<HTMLElement>));

    expect(afterDrag.preventDefault).toHaveBeenCalledTimes(1);
    expect(afterDrag.stopPropagation).toHaveBeenCalledTimes(1);

    // Подавление одноразовое: следующий клик — уже обычное нажатие.
    const tap = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
    act(() => mounted.swipe.handlers.onPointerDown(pointerEvent(container, { clientX: 200 })));
    act(() => mounted.swipe.handlers.onPointerUp(pointerEvent(container, { clientX: 200 })));
    act(() => mounted.swipe.handlers.onClickCapture(tap as unknown as React.MouseEvent<HTMLElement>));
    expect(tap.preventDefault).not.toHaveBeenCalled();
    mounted.unmount();
  });

  it("поле ввода, кнопка и селект не перехватываются", () => {
    for (const tag of ["input", "button", "select", "textarea"]) {
      const mounted = mountSwipe();
      const container = makeContainer();
      const interactive = document.createElement("div");
      const control = document.createElement(tag);
      interactive.appendChild(control);

      drag(mounted.swipe, container, { overrides: { target: control } });

      expect(container.scrollLeft, `${tag} не должен тащить таблицу`).toBe(0);
      expect(container.setPointerCapture).not.toHaveBeenCalled();
      mounted.unmount();
    }
  });

  it("пальцем таблицу не тащим руками: горизонтальную панораму делает браузер", () => {
    const mounted = mountSwipe();
    const container = makeContainer();

    drag(mounted.swipe, container, { overrides: { pointerType: "touch" } });

    expect(container.scrollLeft).toBe(0);
    mounted.unmount();
  });

  it("без горизонтального переполнения жест ничего не делает", () => {
    const mounted = mountSwipe();
    const container = makeContainer({ clientWidth: 900, scrollWidth: 900 });

    drag(mounted.swipe, container);

    expect(container.scrollLeft).toBe(0);
    mounted.unmount();
  });

  it("вертикальное движение не превращается в горизонтальный свайп", () => {
    const mounted = mountSwipe();
    const container = makeContainer();

    act(() => mounted.swipe.handlers.onPointerDown(pointerEvent(container, { clientX: 200, clientY: 10 })));
    act(() => mounted.swipe.handlers.onPointerMove(pointerEvent(container, { clientX: 190, clientY: 90 })));

    expect(container.scrollLeft).toBe(0);
    expect(mounted.swipe.isDragging).toBe(false);
    mounted.unmount();
  });

  it("во время перетаскивания таблица помечена как перетаскиваемая", () => {
    const mounted = mountSwipe();
    const container = makeContainer();

    act(() => mounted.swipe.handlers.onPointerDown(pointerEvent(container, { clientX: 200 })));
    act(() => mounted.swipe.handlers.onPointerMove(pointerEvent(container, { clientX: 150 })));
    expect(mounted.swipe.isDragging).toBe(true);

    act(() => mounted.swipe.handlers.onPointerUp(pointerEvent(container, { clientX: 150 })));
    expect(mounted.swipe.isDragging).toBe(false);
    mounted.unmount();
  });
});

describe("stickyCell", () => {
  it("объявляет имя колонки для E2E и липнет слева", () => {
    const profile = stickyCell({ name: "profile", side: "left" });

    expect(profile["data-sticky"]).toBe("profile");
    expect(profile.className).toContain("max-md:sticky");
    expect(profile.className).toContain("max-md:left-0");
  });

  it("«Действия» липнет справа, а шапка лежит выше ячеек тела", () => {
    const actions = stickyCell({ name: "actions", side: "right" });
    const header = stickyCell({ name: "actions", side: "right", header: true });

    expect(actions.className).toContain("max-md:right-0");
    expect(actions.className).toContain("max-md:z-10");
    expect(header.className).toContain("max-md:z-30");
  });

  it("непрозрачная подложка и уточнения страницы идут рядом с механикой", () => {
    const cell = stickyCell({ name: "profile", side: "left", className: "max-md:bg-card" });

    expect(cell.className).toContain("max-md:bg-card");
    expect(cell.className).toContain("max-md:left-0");
  });
});

describe("MobileScrollTable", () => {
  it("объявляет себя в разметке и отдаёт контейнер наружу", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const scrollRef = { current: null as HTMLDivElement | null };

    act(() => {
      root.render(
        <MobileScrollTable scrollRef={scrollRef} className="extra-class" style={{ maxHeight: "70vh" }}>
          <table>
            <tbody>
              <tr>
                <td>строка</td>
              </tr>
            </tbody>
          </table>
        </MobileScrollTable>,
      );
    });

    const container = host.querySelector("[data-mobile-scroll-table]");
    expect(container).not.toBeNull();
    expect(container?.className).toContain("extra-class");
    expect((container as HTMLElement).style.maxHeight).toBe("70vh");
    expect(container?.querySelector("table")).not.toBeNull();
    expect(scrollRef.current).toBe(container);

    act(() => root.unmount());
    host.remove();
  });
});

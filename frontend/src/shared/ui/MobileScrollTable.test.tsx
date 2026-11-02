// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { fireEvent } from "@testing-library/react";

import { stubViewportWidth } from "@/shared/lib/testViewport";

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

function mountSwipe(options?: { thresholdPx?: number; enabled?: boolean }) {
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

/**
 * Экран и переполнение (#341, ревью 1): жест — только телефон.
 *
 * Обе страницы кладут внутрь `style={{maxHeight:"70vh", overflow:"auto"}}`, и
 * широкая таблица на десктопе тоже переполняет контейнер, поэтому одной
 * проверки «есть что тащить» не хватает: на большом экране мышью водят по
 * строке, чтобы выделить текст и нажать её. Тест рендерит примитив целиком и
 * смотрит единственное, что видно снаружи: сдвинулся ли `scrollLeft`, появился
 * ли `data-dragging` и дошёл ли клик до кнопки строки.
 */

interface RenderedTable {
  container: HTMLElement;
  cell: HTMLElement;
  action: HTMLElement;
  clicks: number;
  unmount: () => void;
}

/** Ширина экрана и переполнение под ним: тест задаёт их вместе. */
const DESKTOP_VIEWPORT = { width: 1280, clientWidth: 1200, scrollWidth: 1600 };
const PHONE_VIEWPORT = { width: 390, clientWidth: 340, scrollWidth: 720 };

function renderTable(viewport: typeof DESKTOP_VIEWPORT): RenderedTable {
  stubViewportWidth(viewport.width);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const scrollRef = { current: null as HTMLDivElement | null };
  const state = { clicks: 0 };

  function Row() {
    const onClick = () => {
      state.clicks += 1;
    };
    return (
      <MobileScrollTable scrollRef={scrollRef} style={{ maxHeight: "70vh", overflow: "auto" }}>
        <table>
          <tbody>
            <tr>
              <td data-testid="cell">артикул</td>
              <td>
                <button type="button" data-testid="action" onClick={onClick}>
                  Завершить
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </MobileScrollTable>
    );
  }

  act(() => root.render(<Row />));

  const container = scrollRef.current;
  if (!container) throw new Error("скролл-контейнер не смонтирован");
  // Раскладки в happy-dom нет: переполнение задаёт сам тест, ровно то условие,
  // при котором примитив сегодня решает «есть что тащить».
  let scrollLeft = 0;
  Object.defineProperty(container, "clientWidth", { value: viewport.clientWidth, configurable: true });
  Object.defineProperty(container, "scrollWidth", { value: viewport.scrollWidth, configurable: true });
  Object.defineProperty(container, "scrollLeft", {
    get: () => scrollLeft,
    set: (value: number) => {
      scrollLeft = value;
    },
    configurable: true,
  });

  return {
    container,
    cell: container.querySelector("[data-testid='cell']") as HTMLElement,
    action: container.querySelector("[data-testid='action']") as HTMLElement,
    get clicks() {
      return state.clicks;
    },
    unmount: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

/** Тот же жест мышью, что делает оператор: нажал, повёл, отпустил, кликнули. */
function pointer(table: RenderedTable, el: HTMLElement, type: "pointerdown" | "pointermove" | "pointerup", clientX: number) {
  act(() => {
    fireEvent(el, new window.PointerEvent(type, { bubbles: true, cancelable: true, clientX, clientY: 42, pointerId: 1, pointerType: "mouse", button: 0 }));
  });
}

function dragOnTable(table: RenderedTable, from: number, delta: number) {
  pointer(table, table.cell, "pointerdown", from);
  pointer(table, table.cell, "pointermove", from - delta);
}

function clickAction(table: RenderedTable) {
  act(() => {
    fireEvent.click(table.action);
  });
}

describe("MobileScrollTable: жест только на телефоне", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("на десктопе переполненная таблица не тащится, не «схватывается» и клик не гаснет", () => {
    const table = renderTable(DESKTOP_VIEWPORT);

    dragOnTable(table, 500, DRAG_THRESHOLD_PX * 4);
    pointer(table, table.cell, "pointerup", 500 - DRAG_THRESHOLD_PX * 4);
    clickAction(table);

    expect(table.container.scrollLeft, "жест мышью не двигает десктопную таблицу").toBe(0);
    expect(table.container.hasAttribute("data-dragging"), "таблица не в состоянии «схватил»").toBe(false);
    expect(table.clicks, "клик доходит до строки").toBe(1);
    table.unmount();
  });

  it("на телефоне тот же жест листает таблицу, а клик после свайпа гасится", () => {
    const table = renderTable(PHONE_VIEWPORT);

    dragOnTable(table, 300, 60);
    expect(table.container.scrollLeft).toBe(60);
    expect(table.container.getAttribute("data-dragging")).toBe("");

    pointer(table, table.cell, "pointerup", 240);
    clickAction(table);
    expect(table.clicks, "синтетический клик после свайпа не нажимает строку").toBe(0);

    // Обычное нажатие после свайпа снова работает.
    clickAction(table);
    expect(table.clicks).toBe(1);
    table.unmount();
  });

  it("хук умеет выключаться явно: обработчики не двигают, не глушат и не отменяют событие", () => {
    const mounted = mountSwipe({ enabled: false });
    const container = makeContainer();
    const move = pointerEvent(container, { clientX: 100 });
    const click = { preventDefault: vi.fn(), stopPropagation: vi.fn() };

    act(() => mounted.swipe.handlers.onPointerDown(pointerEvent(container)));
    act(() => mounted.swipe.handlers.onPointerMove(move));
    act(() => mounted.swipe.handlers.onPointerUp(pointerEvent(container, { clientX: 100 })));
    act(() => mounted.swipe.handlers.onClickCapture(click as unknown as React.MouseEvent<HTMLElement>));

    expect(container.scrollLeft).toBe(0);
    expect(container.setPointerCapture).not.toHaveBeenCalled();
    expect(move.preventDefault).not.toHaveBeenCalled();
    expect(mounted.swipe.isDragging).toBe(false);
    expect(click.preventDefault).not.toHaveBeenCalled();
    mounted.unmount();
  });
});

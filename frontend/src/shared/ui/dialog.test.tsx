import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";

import { Dialog, DialogContent, DialogTitle } from "./dialog";

/**
 * Каркас окна ограничивает высоту по умолчанию (#344).
 *
 * Контракт живёт в строке классов `DialogContent` и держится на `cn`
 * (`clsx` + `tailwind-merge`): потолок высоты и внутренняя прокрутка стоят в
 * базовом наборе, а вызывающий окно перекрывает их своими классами. Проверять
 * это в браузере дорого, а сломать легко: строка классов читается как
 * «просто стили», и удаление двух утилит возвращает баг «кнопки под нижним
 * краем экрана» — молча, потому что ни один тест этого не заметил.
 *
 * Снимок CSS здесь не пинится: проверяется только то, чей класс победил.
 *
 * Второй describe (`✕`) — уже поведение, а не строка классов: каркас обязан
 * компенсировать прокрутку рамки, чтобы кнопка закрытия не уезжала за край
 * экрана. Пользовательский эффект (✕ в кадре после прокрутки живого окна)
 * доказывает `e2e/mobile-dialogs.spec.ts`, здесь пинбуется механизм.
 */

function dialogClasses(className?: string): string {
  const { unmount } = render(
    <Dialog open>
      <DialogContent className={className}>
        <DialogTitle>Окно</DialogTitle>
      </DialogContent>
    </Dialog>,
  );
  const classes = screen.getByRole("dialog").className;
  // Окно снимается вместе с React-деревом: ручное удаление узла оставляет
  // портал Radix живым и следующий `render` падает на «Should not already be
  // working».
  unmount();
  return classes;
}

/** Класс-утилита целиком, а не подстрока: `max-h-screen` не должен матчить `max-h-[90vh]`. */
function hasToken(classes: string, token: string): boolean {
  return classes.split(/\s+/).includes(token);
}

/**
 * Прокрутка рамки в среде без layout-движка.
 *
 * `happy-dom` не считает геометрию: у узла нет ни высоты контента, ни
 * прокрутки, а `scrollTop` — просто число на элементе. Поэтому смещение
 * задаётся own-свойством, а событие `scroll` поставляется руками: тест
 * проверяет не то, что браузер прокрутит рамку (это доказывает
 * `e2e/mobile-dialogs.spec.ts` в живом Chromium), а то, что каркас реагирует
 * на прокрутку рамки и удерживает ✕ у её верхнего края.
 */
function scrollFrame(frame: HTMLElement, top: number): void {
  Object.defineProperty(frame, "scrollTop", { configurable: true, value: top });
  frame.dispatchEvent(new Event("scroll"));
}

function maxHeightToken(classes: string): string | undefined {
  return classes
    .split(/\s+/)
    .filter((token) => token.startsWith("max-h-"))[0];
}

describe("DialogContent — потолок высоты и прокрутка по умолчанию", () => {
  it("без своих классов окно получает потолок высоты и внутреннюю прокрутку", () => {
    const classes = dialogClasses();

    expect(maxHeightToken(classes), "потолок высоты окна").toBe(
      "max-h-[calc(100dvh-2rem)]",
    );
    expect(hasToken(classes, "overflow-y-auto"), "внутренняя прокрутка").toBe(true);
  });

  it("вызывающий перекрывает потолок высоты, прокрутка остаётся", () => {
    // Окно-«шторка» (`h-screen max-h-screen`) — полноэкранная раскладка, свой
    // потолок важнее общего.
    const classes = dialogClasses("h-screen max-h-screen");

    expect(maxHeightToken(classes), "победил класс окна").toBe("max-h-screen");
    expect(hasToken(classes, "max-h-[calc(100dvh-2rem)]")).toBe(false);
    expect(hasToken(classes, "overflow-y-auto"), "прокрутка никуда не ушла").toBe(true);
  });

  it("размер из DIALOG_SIZES перекрывает оба умолчания", () => {
    const classes = dialogClasses(
      `${DIALOG_SIZES.sm.width} ${DIALOG_SIZES.sm.height}`,
    );

    expect(maxHeightToken(classes), "потолок из набора размеров").toBe("max-h-[90vh]");
    expect(hasToken(classes, "w-[92vw]"), "ширина из набора размеров").toBe(true);
    expect(hasToken(classes, "max-h-[calc(100dvh-2rem)]")).toBe(false);
  });

  it("окно со своим прокручиваемым телом снимает общую прокрутку", () => {
    // Импорт-визард и предпросмотр держат прокрутку внутри (`flex-1
    // overflow-auto`): общий `overflow-y-auto` дал бы вторую полосу.
    const classes = dialogClasses("max-h-[85vh] overflow-hidden flex flex-col");

    expect(hasToken(classes, "overflow-hidden"), "прокрутка окна снята").toBe(true);
    expect(hasToken(classes, "overflow-y-auto")).toBe(false);
    expect(maxHeightToken(classes)).toBe("max-h-[85vh]");
  });
});

/**
 * Кнопка закрытия при прокрутке тела (#344, ревью 6).
 *
 * Тело окна прокручивается самой рамкой, а ✕ прижата к её верхнему правому
 * углу. `absolute`-потомок скроллящегося контейнера уезжает вместе с
 * содержимым, поэтому на высоком окне (после поворота телефона) ✕ уползала за
 * верхний край экрана и закрыть окно мышью было нечем. `fixed` не помогает:
 * трансформированная рамка становится для него контейнером, и он прокручивается
 * так же (замерен в Chromium). Значит каркас обязан компенсировать прокрутку.
 */
describe("DialogContent — ✕ не уезжает при прокрутке тела", () => {
  function renderDialog() {
    const tree = render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Окно</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    const frame = screen.getByRole("dialog");
    const close = within(frame).getByRole("button", { name: "Закрыть" });
    return { frame, close, unmount: tree.unmount };
  }

  /**
   * Вертикальное смещение узла в пикселях.
   *
   * Пинится величина компенсации, а не запись: `translateY(120px)` и
   * `translate3d(0, 120px, 0)` — одно и то же поведение, и тест не должен
   * падать при замене одной формы на другую.
   */
  function translateYpx(el: HTMLElement): number {
    const value = el.style.transform.trim();
    if (!value) return 0;
    const oneAxis = /^translateY\(([-\d.]+)px\)$/.exec(value);
    if (oneAxis) return Number(oneAxis[1]);
    const three = /^translate3d\([^,]+,\s*([-\d.]+)px,\s*[^,]+\)$/.exec(value);
    if (three) return Number(three[1]);
    throw new Error(`непонятный transform у ✕: ${value}`);
  }

  it("✕ принадлежит рамке окна, а не содержимому вызывающего", () => {
    const { frame, close, unmount } = renderDialog();

    expect(frame.contains(close), "✕ смонтирована рамкой").toBe(true);
    unmount();
  });

  it("смонтированная непрокрученная рамка не сдвигает ✕", () => {
    const { close, unmount } = renderDialog();

    expect(translateYpx(close), "на нулевой прокрутке ✕ на месте").toBe(0);
    unmount();
  });

  it("компенсация равна прокрутке рамки: при 120px ✕ сдвинута на 120px", () => {
    const { frame, close, unmount } = renderDialog();

    scrollFrame(frame, 120);
    expect(translateYpx(close), "✕ догоняет прокрутку рамки").toBe(120);

    scrollFrame(frame, 0);
    expect(translateYpx(close), "и возвращается на место").toBe(0);
    unmount();
  });

  it("компенсация следует за каждой прокруткой, а не только за первой", () => {
    const { frame, close, unmount } = renderDialog();

    for (const top of [40, 320, 17]) {
      scrollFrame(frame, top);
      expect(translateYpx(close), `прокрутка ${top}px`).toBe(top);
    }
    unmount();
  });

  it("размонтированное окно снимает слушатели и не держит ✕", () => {
    // Незакрытый `ResizeObserver` и висящий слушатель — утечка: узлы окна
    // переживают само окно. Проверяется на уже отсоединённых узлах: если
    // уборка не выполнена, чужой `scroll` всё ещё сдвинет ✕.
    const { frame, close, unmount } = renderDialog();

    scrollFrame(frame, 60);
    expect(translateYpx(close)).toBe(60);

    unmount();
    scrollFrame(frame, 240);
    expect(translateYpx(close), "слушатель снят при размонтировании").toBe(60);
  });
});

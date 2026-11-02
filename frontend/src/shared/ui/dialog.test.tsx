import { render, screen } from "@testing-library/react";
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

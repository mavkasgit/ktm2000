import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogTitle,
} from "./alert-dialog";

/**
 * Каркас `AlertDialog` обязан держать потолок высоты так же, как `Dialog`
 * (#344, ревью 6 — «проверить остальные вызовы DialogContent»).
 *
 * Диалог подтверждения — соседний каркас над теми же примитивами Radix и с той
 * же вёрсткой (`fixed … grid … p-6`), но потолок высоты и внутренняя прокрутка
 * стояли только в `Dialog`. Итог на телефоне: окно подтверждения выше экрана,
 * кнопки «Отмена»/«Удалить» — под нижним краем, а `body` под оверлеем Radix не
 * прокручивается. Проверка здесь — ровно тот же контракт перекрытия классов,
 * что в `dialog.test.tsx`: дублировать хелперы дешевле, чем выдумывать общего
 * поставщика тестовых утилит ради двух функций.
 */

function alertClasses(className?: string): string {
  const { unmount } = render(
    <AlertDialog open>
      <AlertDialogContent className={className}>
        <AlertDialogTitle>Подтверждение</AlertDialogTitle>
        <AlertDialogAction>Удалить</AlertDialogAction>
      </AlertDialogContent>
    </AlertDialog>,
  );
  const classes = screen.getByRole("alertdialog").className;
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

describe("AlertDialogContent — потолок высоты и прокрутка по умолчанию", () => {
  it("без своих классов окно подтверждения получает потолок и прокрутку", () => {
    const classes = alertClasses();

    expect(maxHeightToken(classes), "потолок высоты окна").toBe(
      "max-h-[calc(100dvh-2rem)]",
    );
    expect(hasToken(classes, "overflow-y-auto"), "внутренняя прокрутка").toBe(true);
  });

  it("вызывающий перекрывает потолок высоты, прокрутка остаётся", () => {
    const classes = alertClasses("max-h-[85vh]");

    expect(maxHeightToken(classes), "победил класс окна").toBe("max-h-[85vh]");
    expect(hasToken(classes, "max-h-[calc(100dvh-2rem)]")).toBe(false);
    expect(hasToken(classes, "overflow-y-auto"), "прокрутка никуда не ушла").toBe(true);
  });

  it("окно со своим прокручиваемым телом снимает общую прокрутку", () => {
    const classes = alertClasses("max-h-[90vh] overflow-hidden flex flex-col");

    expect(hasToken(classes, "overflow-hidden"), "прокрутка окна снята").toBe(true);
    expect(hasToken(classes, "overflow-y-auto")).toBe(false);
    expect(maxHeightToken(classes)).toBe("max-h-[90vh]");
  });
});

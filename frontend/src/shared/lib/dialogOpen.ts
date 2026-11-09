/**
 * Проверка, открыто ли сейчас модальное окно или слой, который сам закрывается
 * по Escape.
 *
 * Нужна глобальным обработчикам клавиш страницы. Свои окна они знают по флагам
 * состояния, но список флагов приходится вести вручную, и каждое новое окно
 * добавляет ещё одну забываемую строку: обработчик страницы срабатывает поверх
 * окна и, например, выкидывает оператора с доски.
 *
 * Общий каркас `Dialog` помечает открытое окно `role="dialog"` и
 * `data-state="open"` (Radix), поэтому проверка идёт по DOM и не требует знать
 * про каждое окно. Тем же свойством обладают `AlertDialog` (`alertdialog`) и
 * всплывающие слои Radix, которые тоже закрываются по Escape: меню (`menu`),
 * Select (`listbox`) и Popover (портал `data-radix-popper-content-wrapper`).
 * Их Escape принадлежит слою: страница не должна снимать массовый режим
 * вместе с закрытием меню.
 */

/** Открытые слои, которые забирают Escape себе (Radix). */
const OPEN_ESCAPE_LAYER_SELECTOR = [
  '[role="dialog"][data-state="open"]',
  '[role="alertdialog"][data-state="open"]',
  '[role="menu"][data-state="open"]',
  '[role="listbox"][data-state="open"]',
  '[data-radix-popper-content-wrapper] [data-state="open"]',
].join(", ");

/** Открыт ли сейчас хотя бы один модальный слой. */
export function isAnyDialogOpen(root: ParentNode = document): boolean {
  return root.querySelector(OPEN_ESCAPE_LAYER_SELECTOR) !== null;
}

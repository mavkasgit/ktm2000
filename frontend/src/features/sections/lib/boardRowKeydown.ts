/**
 * lib/boardRowKeydown.ts — клавиатура выбора на доске участка (#283).
 *
 * Enter и пробел переключают выделение строки таблицы и шапки группы. С #345
 * носитель строки один на оба экрана — `<tr>`, — поэтому и обработчик один:
 * три дословные копии в `SectionTasksBoard` расходились бы при первой правке
 * (ревью R05, п. 5).
 *
 * Клавиша, нажатая внутри строки — в поле количества или в кнопке «Завершить», —
 * строку не трогает: Enter на кнопке обязан открыть диалог, а не переключить
 * выделение.
 */

/** Что обработчику нужно от события — структурно, без зависимости от React. */
export type SelectionKeyEvent = {
  key: string;
  target: EventTarget | null;
  currentTarget: EventTarget | null;
  preventDefault: () => void;
};

/**
 * Enter/пробел на самом носителе строки — тумблер выделения. Возвращает
 * `true`, если нажатие обработано; событие из вложенного поля или кнопки и
 * любая другая клавиша остаются нетронутыми.
 */
export function toggleSelectionOnRowKey(
  event: SelectionKeyEvent,
  toggle: () => void,
): boolean {
  if (event.target !== event.currentTarget) return false;
  if (event.key !== "Enter" && event.key !== " ") return false;
  // Пробел не прокручивает страницу, Enter не нажимает «первую» кнопку.
  event.preventDefault();
  toggle();
  return true;
}

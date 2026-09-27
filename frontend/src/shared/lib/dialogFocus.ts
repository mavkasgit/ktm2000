/**
 * Источник открытия окна — для возврата фокуса при закрытии.
 *
 * Общий каркас `Dialog` возвращает фокус на тот элемент, который был активен
 * в момент монтирования окна. На практике это `body`: между кликом по кнопке
 * и монтированием окна страница успевает перерисоваться, активный элемент
 * теряет фокус, и каркас запоминает `body`. Возврат фокуса после этого
 * работает, но возвращает не туда — оператор оказывается в начале страницы.
 *
 * Поэтому источник запоминается раньше: на `pointerdown` и на `keydown`
 * (активация с клавиатуры) в фазе захвата, когда фокус ещё на кнопке.
 * Слушатели ставятся один раз в оболочке приложения.
 *
 * Запоминается не один элемент, а короткий стек: закрыть окно можно и `Escape`,
 * и кликом по кнопке внутри окна — тогда последним запомненным окажется элемент
 * самого окна, который к моменту возврата уже отсоединён. Поэтому берётся
 * последний ещё живой элемент стека, а не буквально последний.
 */

/** Последние элементы, которыми пользователь взаимодействовал. От новых к старым. */
const recent: HTMLElement[] = [];
const MAX_RECENT = 8;
let installed = false;

/** Что можно сфокусировать. */
const INTERACTIVE =
  "a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])";

function remember(event: Event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  // Событие приходит по самому глубокому узлу: иконке, просуту, подписи.
  // Фокусировать их нельзя, поэтому источник — ближайший интерактивный предок.
  const source = target.closest<HTMLElement>(INTERACTIVE) ?? target;
  const index = recent.indexOf(source);
  if (index >= 0) recent.splice(index, 1);
  recent.push(source);
  if (recent.length > MAX_RECENT) recent.shift();
}

export function installDialogFocusTracker(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;
  document.addEventListener("pointerdown", remember, true);
  document.addEventListener("keydown", remember, true);
}

/**
 * Забрать источник открытия окна: последний ещё живой элемент стека. Элемент,
 * который к моменту закрытия отсоединён, пропускается — вернуть на него фокус
 * уже некуда.
 */
export function takeDialogTrigger(): HTMLElement | null {
  while (recent.length > 0) {
    const candidate = recent.pop();
    if (candidate?.isConnected) return candidate;
  }
  return null;
}

/** Сброс в тестах. */
export function resetDialogTrigger(): void {
  recent.length = 0;
}

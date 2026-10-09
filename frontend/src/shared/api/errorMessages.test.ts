import { describe, expect, it } from "vitest";

import { getErrorHint, translateError } from "./errorMessages";

describe("translateError", () => {
  it("returns empty string for empty input", () => {
    expect(translateError("")).toBe("");
    expect(translateError(null)).toBe("");
    expect(translateError(undefined)).toBe("");
  });

  it("translates the canonical 'Task must be in progress' string", () => {
    expect(translateError("Task must be in progress")).toBe("Задача должна быть в работе");
  });

  it("translates all three variants of the task status error", () => {
    expect(translateError("Task must be in progress")).toBe("Задача должна быть в работе");
    expect(translateError("Task must be ready/in_progress/partially_completed"))
      .toBe("Задача должна быть в статусе «готова», «в работе» или «частично завершена»");
  });

  it("translates the Section is locked to single-window context message", () => {
    expect(translateError("Section is locked to single-window context"))
      .toBe("Режим одного окна разрешает работу только с текущим участком");
  });

  it("returns original string when no translation found", () => {
    expect(translateError("Some unknown english message")).toBe("Some unknown english message");
  });

  it("handles f-string templates with positional placeholders", () => {
    expect(translateError("Return quantity (1.5) exceeds available for return (2.0)"))
      .toBe("Количество возврата (1.5) превышает доступное к возврату (2.0)");
  });

  it("handles templates with quoted values", () => {
    expect(translateError("Position with status 'draft' cannot be approved"))
      .toBe("Позиция в статусе «draft» не может быть утверждена");
  });

  it("preserves original casing for unknown Cyrillic messages", () => {
    expect(translateError("Случайное сообщение")).toBe("Случайное сообщение");
  });
});

/**
 * Таблица — по подсказке на строку (#323): первый элемент — текст, который
 * реально приходит с сервера (проверено по `raise ValueError`/`HTTPException`),
 * второй — то, что видит оператор. Подсказка ищется и в сыром виде, и после
 * `translateError`, поэтому обе половины каждой строки проверяются.
 */
const HINT_CASES: [string, string][] = [
  [
    "Complete quantity exceeds quantity in work",
    "Количество факта больше объема 'В работе'. Сначала уменьшите факт или довыдайте в работу.",
  ],
  [
    "Return quantity (1.5) exceeds available for return (2.0)",
    "Количество больше доступного для выдачи. Проверьте поле 'Доступно'.",
  ],
  [
    "Section is locked to single-window context",
    "Режим одного окна разрешает работу только с текущим участком.",
  ],
  ["Transfer quantity exceeds transferable amount", "Количество больше доступного к передаче."],
  [
    "Corrected quantity exceeds transferable amount of source task. Available to transfer: 3.5",
    "Количество больше доступного к передаче.",
  ],
  [
    "Transfer target must be next route step",
    "Передавать можно только на следующий этап маршрута.",
  ],
  ["Transfer must be sent", "Передача уже обработана. Обновите список входящих передач."],
  [
    "accepted + rejected exceeds sent quantity",
    "Сумма принятого и отклонённого превышает отправленное количество.",
  ],
  ["Final release exceeds releasable quantity", "Количество больше доступного к выпуску."],
  [
    "Final release allowed only for final route stage",
    "Финальный выпуск доступен только на финальном этапе маршрута.",
  ],
  [
    "Target task has already consumed or issued parts. Cannot reduce transfer by 2 as target task only has 1 available stock",
    "Нельзя уменьшить передачу: целевая задача уже использовала материалы.",
  ],
];

describe("getErrorHint", () => {
  it("returns null for empty input", () => {
    expect(getErrorHint("")).toBeNull();
    expect(getErrorHint(null)).toBeNull();
    expect(getErrorHint(undefined)).toBeNull();
  });

  it.each(HINT_CASES)("hints on raw server text: %s", (serverText, hint) => {
    expect(getErrorHint(serverText)).toBe(hint);
  });

  it.each(HINT_CASES)("hints on translated text (the page gets this): %s", (serverText, hint) => {
    // Через `translateError` — так текст приходит в страницу из `getErrorMessage`.
    // Перевод обязателен: без ключа в словаре обратный поиск не найдёт подсказку,
    // и тест упадёт (сторож «подсказка не осталась недостижимой»).
    const translated = translateError(serverText);
    expect(translated).not.toBe(serverText);
    expect(getErrorHint(translated)).toBe(hint);
  });

  it("returns null when no hint is known for the message", () => {
    expect(getErrorHint("Some unknown english message")).toBeNull();
    expect(getErrorHint(translateError("Task must be in progress"))).toBeNull();
    expect(getErrorHint("Задача должна быть в работе")).toBeNull();
  });
});

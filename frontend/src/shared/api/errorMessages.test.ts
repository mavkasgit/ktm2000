import { describe, expect, it } from "vitest";

import { translateError } from "./errorMessages";

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

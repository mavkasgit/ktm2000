import { describe, expect, it } from "vitest";

import { messagePairLayout } from "./messageColumns";

describe("messagePairLayout", () => {
  it("только ошибки: ошибки занимают обе колонки пары", () => {
    expect(messagePairLayout(true, false)).toEqual({
      errorsColSpan: 2,
      warningsColSpan: 0,
      precedingColSpan: 1,
    });
  });

  it("только предупреждения: предупреждения занимают обе колонки пары", () => {
    expect(messagePairLayout(false, true)).toEqual({
      errorsColSpan: 0,
      warningsColSpan: 2,
      precedingColSpan: 1,
    });
  });

  it("оба типа: каждое сообщение в своей колонке", () => {
    expect(messagePairLayout(true, true)).toEqual({
      errorsColSpan: 1,
      warningsColSpan: 1,
      precedingColSpan: 1,
    });
  });

  it("ничего не показано: пару забирает колонка перед ней", () => {
    expect(messagePairLayout(false, false)).toEqual({
      errorsColSpan: 0,
      warningsColSpan: 0,
      precedingColSpan: 3,
    });
  });

  it("три слота заняты всегда — иначе строка съезжает", () => {
    for (const errorsShown of [true, false]) {
      for (const warningsShown of [true, false]) {
        const layout = messagePairLayout(errorsShown, warningsShown);
        const slots =
          layout.errorsColSpan + layout.warningsColSpan + layout.precedingColSpan;
        expect(slots, `errors=${errorsShown}, warnings=${warningsShown}`).toBe(3);
      }
    }
  });
});

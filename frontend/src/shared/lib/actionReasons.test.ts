/**
 * Словарь причин недоступности (#193).
 *
 * Контракт потребительский: по коду оператор читает на экране текст, который
 * объясняет, почему действие не нажимается, и разные причины не soundят
 * одинаково — иначе оператор не отличит «сырьё не поступило» от «задание
 * отменено» и не поймёт, что делать. Формулировки не пиним: они меняются.
 */

import { describe, expect, it } from "vitest";

import { ACTION_REASON_TEXT, actionReasonText, type ActionReasonCode } from "./actionReasons";

const CODES = Object.keys(ACTION_REASON_TEXT) as ActionReasonCode[];

describe("actionReasonText", () => {
  it("разные причины звучат по-разному: одинаковые тексты сливают их в одну", () => {
    const seen = new Map<string, ActionReasonCode>();
    for (const code of CODES) {
      const text = actionReasonText(code);
      const clash = seen.get(text);
      expect(clash, `коды «${clash ?? ""}» и «${code}» дают один текст «${text}»`).toBeUndefined();
      seen.set(text, code);
    }
  });

  it("отсутствие причины — это null, а не пустая строка и не текст-заглушка", () => {
    expect(actionReasonText(null)).toBeNull();
    expect(actionReasonText(undefined)).toBeNull();
  });
});

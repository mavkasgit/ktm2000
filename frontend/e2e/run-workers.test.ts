/**
 * Разбор `--workers` в прогоне E2E (#289).
 *
 * Что тут ловится. Число воркеров — не только настройка Playwright: столько
 * же должно быть клонов БД (`e2e:prep --workers N`) и backend'ов
 * (`scripts/run-e2e.mjs`). Если форма нераспознанная и разбор молча даёт 1,
 * Playwright запускает N воркеров на одном клоне, `apiResetAll()` сносит
 * соседу данные, и симптом — флейки, а не ошибка. Разбор поэтому обязан
 * падать, а не угадывать.
 *
 * Модуль `run-workers.mjs` вынесен из `run-tier.mjs` ровно ради этих тестов:
 * сам скрипт — точка входа прогона, его импорт запускает стенд.
 */
import { describe, expect, it } from "vitest";

import { parseWorkersArg } from "./run-workers.mjs";

describe("parseWorkersArg — формы, которые Playwright понимает целиком", () => {
  it("без --workers — один воркер (дефолт конфига)", () => {
    expect(parseWorkersArg([])).toBe(1);
    expect(parseWorkersArg(["--headed", "-g", "смена"])).toBe(1);
  });

  it("читает `--workers=N` — основная форма ночных прогонов", () => {
    expect(parseWorkersArg(["--workers=1"])).toBe(1);
    expect(parseWorkersArg(["--workers=2", "--headed"])).toBe(2);
    expect(parseWorkersArg(["--headed", "--workers=4"])).toBe(4);
  });

  it("читает `--workers N` через пробел — эта форма раньше давала один клон", () => {
    expect(parseWorkersArg(["--workers", "3"])).toBe(3);
  });

  it("читает короткую форму Playwright `-j`", () => {
    expect(parseWorkersArg(["-j", "2"])).toBe(2);
    expect(parseWorkersArg(["-j=2"])).toBe(2);
  });
});

describe("parseWorkersArg — отказ вместо молчаливого отката к одному воркеру", () => {
  it("процент отвергает: клонов под процент столько не выдать", () => {
    expect(() => parseWorkersArg(["--workers=50%"])).toThrow(/процент/i);
    expect(() => parseWorkersArg(["--workers", "50%"])).toThrow(/процент/i);
    expect(() => parseWorkersArg(["-j=50%"])).toThrow(/процент/i);
  });

  it("`--workers` без значения отвергает: дефолт Playwright — 50% ядер", () => {
    expect(() => parseWorkersArg(["--workers"])).toThrow(/без значения/);
    expect(() => parseWorkersArg(["-j"])).toThrow(/без значения/);
  });

  it("нераспознанная форма отвергает, а не считается единицей", () => {
    expect(() => parseWorkersArg(["-j2"])).toThrow(/нераспознанная форма/i);
    expect(() => parseWorkersArg(["--workers2"])).toThrow(/нераспознанная форма/i);
  });

  it("не-целое и неположительное отвергает", () => {
    expect(() => parseWorkersArg(["--workers=abc"])).toThrow(/не целое число/i);
    expect(() => parseWorkersArg(["--workers=2.5"])).toThrow(/не целое число/i);
    expect(() => parseWorkersArg(["--workers=0"])).toThrow(/хотя бы один/);
  });

  it("текст отказа объясняет, что делать", () => {
    expect(() => parseWorkersArg(["--workers=50%"])).toThrow(/--workers=2/);
  });
});

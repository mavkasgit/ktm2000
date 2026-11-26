/**
 * Загрузка веб-шрифтов стенда до первого `prepare()`.
 *
 * `pretext` меряет canvas-движком: если WOFF2 ещё не загружен, он тихо
 * измерит fallback-шрифт, и модель соврёт на всей выборке. Поэтому стенд
 * сначала грузит лица явно (`document.fonts.load`), дожидается
 * `document.fonts.ready` и проверяет `status === "loaded"`.
 *
 * Общий модуль для обоих стендов: H4 (`main.mjs`) и рантайм-замера
 * (`runtime.mjs`, #483).
 */
import { FONT_PX } from "../lib/measurers.mjs";

/** Строка покрывает кириллицу, латиницу, цифры и типографские знаки листа. */
export const FONT_SAMPLE = "АБВГДабвгдЁё 0123456789 .,—№ %";

/**
 * @param {number} weight вес шрифта (`400` — контракт H4, `500` — «Ошибки»)
 * @returns {Promise<{sans: object, mono: object}>}
 */
export async function loadFonts(weight = 400) {
  const [inter, mono] = await Promise.all([
    document.fonts.load(`${weight} ${FONT_PX}px "Inter"`, FONT_SAMPLE),
    document.fonts.load(`${weight} ${FONT_PX}px "JetBrains Mono"`, FONT_SAMPLE),
  ]);
  await document.fonts.ready;

  const describe = (family, faces) => ({
    family,
    weight,
    faces: faces.length,
    loaded: faces.length > 0 && faces.every((face) => face.status === "loaded"),
    check: document.fonts.check(`${weight} ${FONT_PX}px "${family}"`, FONT_SAMPLE),
  });

  const fonts = {
    sans: describe("Inter", inter),
    mono: describe("JetBrains Mono", mono),
  };
  if (!fonts.sans.loaded || !fonts.mono.loaded) {
    throw new Error(
      `webfont не загрузился: ${JSON.stringify(fonts)} — измерять fallback бессмысленно`,
    );
  }
  return fonts;
}

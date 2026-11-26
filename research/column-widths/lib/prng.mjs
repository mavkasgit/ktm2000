/**
 * Детерминированный PRNG для воспроизводимых синтетических листов.
 *
 * Результат бенча обязан повторяться по seed: без этого нельзя ни сравнить
 * оптимизаторы, ни доказать, что изменение ширины — заслуга алгоритма, а не
 * другой выборки.
 */

/** mulberry32 — быстрый seeded PRNG с 32-битным состоянием. */
export function createRng(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function randInt(rng, min, maxInclusive) {
  return min + Math.floor(rng() * (maxInclusive - min + 1));
}

export function pick(rng, items) {
  return items[Math.floor(rng() * items.length)];
}

/** Нормальное распределение (Box–Muller) — для длин «как в реальных данных». */
export function normal(rng, mean = 0, sigma = 1) {
  const u = Math.max(rng(), 1e-12);
  const v = rng();
  return mean + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Log-normal — длинный хвост: большинство коротких, редкие очень длинные. */
export function logNormal(rng, median, sigma) {
  return median * Math.exp(normal(rng, 0, sigma));
}

export function shuffle(rng, items) {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

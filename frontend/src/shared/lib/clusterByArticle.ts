/**
 * clusterByArticle.ts — общий порядок блоков «по количеству, но одинаковые
 * артикулы рядом».
 *
 * Порядок «просто по количеству» ставит один и тот же артикул в два места
 * списка: между его строками вклиниваются чужие, и знакомые оператору строки
 * читаются вразброс. Поэтому блоки (свёрнутые группы и одиночные строки)
 * раскладываются по артикулам: сначала все блоки одного артикула подряд, затем
 * следующий артикул — по сумме количества убыв.
 *
 * У равных сумм первым идёт артикул, чей блок встретился раньше: `sort` устойчив,
 * а `Map` хранит порядок вставки. Порядок блоков внутри артикула сохраняется —
 * он уже пришёл по количеству (из ответа сервера или из сортировки экрана).
 *
 * Одна реализация на все экраны: доска участка, передачи, печатный план. Своя
 * копия рядом с экраном — способ разойтись в том, что «одинаковые артикулы
 * близко» значит на соседней странице.
 *
 * Ключ группировки — ``skuLoose`` артикула (#474): ``ALS-1103`` и ``ALS1103``
 * — один артикул, дефис между буквой и цифрой это оформление. В подписи
 * остаётся первое встреченное сырое написание — его и увидит оператор; дефис
 * между цифрами (``12-34``) ключ не снимает, это часть номера.
 */

import { skuLoose } from "./skuSpelling";

export type ClusterByArticleOptions<T> = {
  /** Артикул блока: по нему блоки склеиваются в один кусок списка. */
  articleOf: (block: T) => string;
  /** Количество блока: по сумме артикулов и строится порядок. */
  quantityOf: (block: T) => number;
  /**
   * Порядок артикулов при равной сумме. Не задан — сохраняется порядок
   * первого появления (устойчивая сортировка).
   */
  compareArticles?: (a: string, b: string) => number;
};

export function clusterByArticle<T>(
  blocks: readonly T[],
  { articleOf, quantityOf, compareArticles }: ClusterByArticleOptions<T>,
): T[] {
  const byArticle = new Map<string, T[]>();
  const totals = new Map<string, number>();
  // Первое встреченное написание артикула — для подписи и порядка при равной
  // сумме. Ключ группировки нормализован, а оператору показываем его.
  const displayArticle = new Map<string, string>();

  for (const block of blocks) {
    const article = articleOf(block);
    const key = skuLoose(article);
    const quantity = quantityOf(block);
    const known = byArticle.get(key);
    if (known) {
      known.push(block);
      totals.set(key, (totals.get(key) ?? 0) + quantity);
      continue;
    }
    byArticle.set(key, [block]);
    totals.set(key, quantity);
    displayArticle.set(key, article);
  }

  return [...byArticle.keys()]
    .sort((a, b) => {
      const quantityDiff = (totals.get(b) ?? 0) - (totals.get(a) ?? 0);
      if (quantityDiff !== 0) return quantityDiff;
      return compareArticles
        ? compareArticles(displayArticle.get(a) ?? "", displayArticle.get(b) ?? "")
        : 0;
    })
    .flatMap((article) => byArticle.get(article) ?? []);
}

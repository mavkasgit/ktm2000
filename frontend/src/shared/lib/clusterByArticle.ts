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
 */

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

  for (const block of blocks) {
    const article = articleOf(block);
    const quantity = quantityOf(block);
    const known = byArticle.get(article);
    if (known) {
      known.push(block);
      totals.set(article, (totals.get(article) ?? 0) + quantity);
      continue;
    }
    byArticle.set(article, [block]);
    totals.set(article, quantity);
  }

  return [...byArticle.keys()]
    .sort((a, b) => {
      const quantityDiff = (totals.get(b) ?? 0) - (totals.get(a) ?? 0);
      if (quantityDiff !== 0) return quantityDiff;
      return compareArticles ? compareArticles(a, b) : 0;
    })
    .flatMap((article) => byArticle.get(article) ?? []);
}

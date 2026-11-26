import { describe, expect, it } from "vitest";

import { clusterByArticle } from "./clusterByArticle";

type Block = { article: string; quantity: number; tag: string };

const byArticle = (block: Block) => block.article;
const quantity = (block: Block) => block.quantity;

describe("clusterByArticle", () => {
  it("ставит блоки одного артикула подряд, артикулы — по сумме количества", () => {
    const blocks: Block[] = [
      { article: "АА-1", quantity: 100, tag: "a1" },
      { article: "ББ-2", quantity: 900, tag: "b1" },
      { article: "АА-1", quantity: 100, tag: "a2" },
      { article: "ББ-2", quantity: 900, tag: "b2" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.tag)).toEqual([
      "b1",
      "b2",
      "a1",
      "a2",
    ]);
  });

  it("сохраняет порядок блоков внутри артикула", () => {
    const blocks: Block[] = [
      { article: "АА-1", quantity: 300, tag: "first" },
      { article: "АА-1", quantity: 100, tag: "second" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.tag)).toEqual([
      "first",
      "second",
    ]);
  });

  it("при равных суммах первым идёт артикул, чей блок встретился раньше", () => {
    const blocks: Block[] = [
      { article: "ББ-2", quantity: 500, tag: "b" },
      { article: "АА-1", quantity: 500, tag: "a" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.article)).toEqual([
      "ББ-2",
      "АА-1",
    ]);
  });

  it("суммирует количество по всем блокам артикула, а не сравнивает блоки", () => {
    // Три мелких блока одного артикула перевешивают два крупных чужого.
    const blocks: Block[] = [
      { article: "ЧУЖ-9", quantity: 400, tag: "other" },
      { article: "АА-1", quantity: 300, tag: "a1" },
      { article: "АА-1", quantity: 300, tag: "a2" },
      { article: "АА-1", quantity: 300, tag: "a3" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.tag)).toEqual([
      "a1",
      "a2",
      "a3",
      "other",
    ]);
  });

  it("одинаковые артикулы в разных написаниях — один блок (#474)", () => {
    // `ALS-1103` и `ALS1103` — один артикул: дефис между буквой и цифрой
    // оформление. Группировка по сырому написанию развела бы их в два блока,
    // и знакомые оператору строки читались бы вразброс.
    const blocks: Block[] = [
      { article: "ALS-1103", quantity: 100, tag: "dash" },
      { article: "ALS1103", quantity: 200, tag: "solid" },
      { article: "ЮП-1", quantity: 50, tag: "other" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.tag)).toEqual([
      "dash",
      "solid",
      "other",
    ]);
  });

  it("дефис между цифрами остаётся частью номера: 12-34 и 1234 — разные", () => {
    const blocks: Block[] = [
      { article: "12-34", quantity: 100, tag: "dash" },
      { article: "1234", quantity: 200, tag: "solid" },
    ];

    expect(clusterByArticle(blocks, { articleOf: byArticle, quantityOf: quantity }).map((b) => b.tag)).toEqual([
      "solid",
      "dash",
    ]);
  });

  it("пустой список не падает", () => {
    expect(clusterByArticle([], { articleOf: byArticle, quantityOf: quantity })).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { CutLayoutCell } from "./CutLayoutCell";

/**
 * Распилы, отрендеренные ОТДЕЛЬНЫМИ элементами внутри контейнера-столбца.
 * Склейка распилов в одну строку делает контейнер невалидным и роняет тест.
 */
function cutLines(html: string): string[] {
  const container = html.match(
    /<span class="[^"]*flex-col[^"]*">((?:<span>[^<]*<\/span>)+)<\/span>/,
  );
  if (!container) throw new Error(`Контейнер распилов не найден в разметке: ${html}`);
  return [...container[1].matchAll(/<span>([^<]*)<\/span>/g)].map((m) => m[1]);
}

describe("CutLayoutCell — колонка «Размер»", () => {
  it("renders fallback, or em dash without it, when there is no layout", () => {
    expect(
      renderToStaticMarkup(<CutLayoutCell layout={null} fallback="10 м" />),
    ).toBe("<span>10 м</span>");
    expect(
      renderToStaticMarkup(
        <CutLayoutCell layout={{ input: null, outputs: [] }} fallback="10 м" />,
      ),
    ).toBe("<span>10 м</span>");
    expect(renderToStaticMarkup(<CutLayoutCell />)).toBe("<span>—</span>");
    expect(
      renderToStaticMarkup(<CutLayoutCell layout={{ input: null, outputs: [] }} />),
    ).toBe("<span>—</span>");
  });

  it("renders a single input label without arrow or cut lines when outputs are empty", () => {
    const html = renderToStaticMarkup(
      <CutLayoutCell layout={{ input: "2,75 м", outputs: [] }} />,
    );

    expect(html).toBe("<span>2,75 м</span>");
  });

  it("renders the arrow right after the input and one element per cut line, in order", () => {
    const html = renderToStaticMarkup(
      <CutLayoutCell layout={{ input: "2,75", outputs: ["0,9×50", "1,35×100"] }} />,
    );

    // Стрелка — отдельный элемент внутри общей обёртки, сразу перед столбцом распилов.
    expect(html).toMatch(
      /<span class="[^"]*">2,75 →<\/span><span class="[^"]*flex-col[^"]*">/,
    );
    expect(cutLines(html)).toEqual(["0,9×50", "1,35×100"]);
  });

  it("renders cut lines stacked without input when input is null", () => {
    const html = renderToStaticMarkup(
      <CutLayoutCell layout={{ input: null, outputs: ["0,9×50", "1,35×100"] }} />,
    );

    expect(html).not.toContain("→");
    expect(cutLines(html)).toEqual(["0,9×50", "1,35×100"]);
  });
});

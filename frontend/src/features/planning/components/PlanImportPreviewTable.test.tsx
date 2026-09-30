import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { ImportRowExpansion } from "@/shared/ui/import-utils";

import { PlanImportPreviewTable } from "./PlanImportPreviewTable";

// Статический рендер использует из expansion только isRowExpanded/toggleRow.
const expansionStub = {
  isRowExpanded: () => false,
  toggleRow: () => {},
} as unknown as ImportRowExpansion;

const TONES = ["red", "green", "yellow", "orange"] as const;

// Ожидаемый тон по hanger_source; "" — неизвестное значение без подсветки.
const TONE_BY_SOURCE: Record<string, (typeof TONES)[number] | undefined> = {
  missing_product: "red",
  auto: "green",
  manual: "yellow",
  none: "orange",
  "": undefined,
};

function renderSkuCell(hangerSource: string): { tdClass: string; spanClass: string | null } {
  const row = {
    source_row_number: 7,
    status: "valid",
    errors: [],
    warnings: [],
    after_data: {
      source_sku: "SKU-TONE",
      source_name: "Артикул для проверки подсветки",
      hanger_source: hangerSource,
      quantity: "10",
    },
  };

  const html = renderToStaticMarkup(
    <PlanImportPreviewTable
      rows={[row]}
      expansion={expansionStub}
      hasActiveFilters={false}
      onReset={() => {}}
    />,
  );

  const cell = html.match(
    /<td class="([^"]*)">(?:<span class="([^"]*)">SKU-TONE<\/span>|SKU-TONE)<\/td>/,
  );
  if (!cell) throw new Error(`Ячейка артикула не найдена в разметке: ${html}`);
  return { tdClass: cell[1], spanClass: cell[2] ?? null };
}

describe("PlanImportPreviewTable", () => {
  it("highlights the sku span by after_data.hanger_source without tinting the td", () => {
    for (const [hangerSource, tone] of Object.entries(TONE_BY_SOURCE)) {
      const label = `hanger_source=${hangerSource || "(пусто)"}`;
      const { tdClass, spanClass } = renderSkuCell(hangerSource);

      // Ячейка артикула не заливается ни при каком источнике.
      expect(tdClass, label).toContain("p-2");
      for (const t of TONES) {
        expect(tdClass, `${label}: td не должен нести фон ${t}`).not.toContain(`bg-${t}-100`);
        expect(tdClass, `${label}: td не должен нести текст ${t}`).not.toContain(`text-${t}-900`);
        expect(tdClass, `${label}: td не должен нести обводку ${t}`).not.toContain(`border-${t}-300`);
        expect(tdClass, `${label}: td не должен нести цвет текста ${t}`).not.toContain(`text-${t}-700`);
      }

      if (!tone) {
        // Неизвестный источник → голый текст без span.
        expect(spanClass, label).toBeNull();
        continue;
      }

      expect(spanClass, label).not.toBeNull();
      expect(spanClass, label).toContain(`text-${tone}-700`);
      expect(spanClass, label).toContain(`border-${tone}-300`);
      expect(spanClass, label).toContain("inline-block");
      expect(spanClass, label).toContain("rounded border ");
      expect(spanClass, label).toContain("px-1");
      expect(spanClass, label).toContain("font-semibold");

      for (const foreign of TONES.filter((t) => t !== tone)) {
        expect(spanClass, `${label}: чужой цвет текста ${foreign}`).not.toContain(`text-${foreign}-700`);
        expect(spanClass, `${label}: чужая обводка ${foreign}`).not.toContain(`border-${foreign}-300`);
      }
      for (const t of TONES) {
        expect(spanClass, `${label}: span — только текст и обводка, без фона ${t}`).not.toContain(
          `bg-${t}-100`,
        );
      }
    }
  });
});

/** Текст строки превью без разметки: теги и SSR-разделители выражений. */
function rowText(overrides: Record<string, unknown>): string {
  const row = {
    source_row_number: 5,
    status: "valid",
    errors: [],
    warnings: [],
    payload: {},
    after_data: {
      source_sku: "ЮП-460",
      source_name: "Профиль ЮП-460",
      route_name: "ГП - Серебро - Стрейч",
      route_source: "dynamic_build",
      route_origin: "auto",
      route_match_quality: "exact",
      quantity: "144",
      ...overrides,
    },
  };

  const html = renderToStaticMarkup(
    <PlanImportPreviewTable
      rows={[row]}
      expansion={expansionStub}
      hasActiveFilters={false}
      onReset={() => {}}
    />,
  );
  return html.replace(/<!-- -->/g, "").replace(/<[^>]*>/g, "");
}

describe("PlanImportPreviewTable — колонка «Кол-во» и маршрут", () => {
  it("показывает сырьё с подвесами и итог так же, как страница плана", () => {
    const text = rowText({
      quantity: "144",
      original_quantity: "100",
      input_quantity: "100",
      quantity_per_hanger: 72,
    });

    expect(text).toContain("100 (2П)-144");
  });

  it("без нормы на подвес диапазон остаётся, подвесы не пишутся", () => {
    const text = rowText({ quantity: "250", input_quantity: "150", quantity_per_hanger: null });

    expect(text).toContain("150-250");
    expect(text).not.toContain("П)");
  });

  it("пишет только название маршрута, без источника и даты", () => {
    const text = rowText({});

    expect(text).toContain("ГП - Серебро - Стрейч");
    expect(text).not.toContain("динамический");
    expect(text).not.toContain("автомаппинг");
    expect(text).not.toContain("15.09.2026");
  });
});

/** Ячейка сообщений в отрендеренной разметке: `colSpan` и текст без тегов. */
function messageCell(html: string, tone: "red" | "amber"): { colSpan: number; text: string } | null {
  const match = html.match(
    new RegExp(`<td([^>]*)class="([^"]*text-${tone}-600[^"]*)"([^>]*)>(.*?)</td>`),
  );
  if (!match) return null;
  return {
    // SSR отдаёт атрибут как `colSpan`, поэтому регистр не важен.
    colSpan: Number(`${match[1]}${match[3]}`.match(/colspan="(\d+)"/i)?.[1] ?? 1),
    text: match[4].replace(/<!-- -->/g, "").replace(/<[^>]*>/g, " ").trim(),
  };
}

/** Пара «Ошибки»/«Предупр.» одной строки в виде `colSpan|текст` либо null. */
function messageCells(row: Record<string, unknown>): { errors: string | null; warnings: string | null } {
  const html = renderToStaticMarkup(
    <PlanImportPreviewTable
      rows={[
        {
          source_row_number: 5,
          status: "warning",
          payload: {},
          after_data: { source_sku: "ЮП-460", source_name: "Профиль", route_name: "ГП - Серебро" },
          ...row,
        },
      ]}
      expansion={expansionStub}
      hasActiveFilters={false}
      onReset={() => {}}
    />,
  );

  const errors = messageCell(html, "red");
  const warnings = messageCell(html, "amber");
  return {
    errors: errors && `${errors.colSpan}|${errors.text}`,
    warnings: warnings && `${warnings.colSpan}|${warnings.text}`,
  };
}

/** Разметка строки превью целиком — нужна для `title` и обрезки. */
function messageRowHtml(row: Record<string, unknown>): string {
  return renderToStaticMarkup(
    <PlanImportPreviewTable
      rows={[
        {
          source_row_number: 5,
          status: "warning",
          payload: {},
          after_data: { source_sku: "ЮП-460", source_name: "Профиль", route_name: "ГП - Серебро" },
          ...row,
        },
      ]}
      expansion={expansionStub}
      hasActiveFilters={false}
      onReset={() => {}}
    />,
  );
}

describe("PlanImportPreviewTable — пара «Ошибки»/«Предупр.»", () => {
  it("только предупреждение занимает обе колонки пары", () => {
    const cells = messageCells({ errors: [], warnings: ["hanger_quantity_not_set:2.7"] });

    expect(cells.errors).toBeNull();
    expect(cells.warnings).toMatch(/^2\|/);
    expect(cells.warnings).toContain("Не задано количество на подвес");
  });

  it("только ошибка занимает обе колонки пары", () => {
    const cells = messageCells({ errors: ["product_not_found"], warnings: [] });

    expect(cells.errors).toMatch(/^2\|/);
    expect(cells.warnings).toBeNull();
  });

  it("оба типа — по одной колонке, у каждого блока свой title", () => {
    const html = messageRowHtml({
      errors: ["product_not_found", "quantity_must_be_positive"],
      warnings: ["hanger_quantity_not_set:2.7"],
    });

    const cells = messageCells({
      errors: ["product_not_found", "quantity_must_be_positive"],
      warnings: ["hanger_quantity_not_set:2.7"],
    });
    expect(cells.errors).toMatch(/^1\|/);
    expect(cells.warnings).toMatch(/^1\|/);

    // Обрезка двумя строками; полный текст каждого блока — в своём title.
    expect(html).toContain("line-clamp-2");
    const titles = [...html.matchAll(/title="([^"]*)"/g)].map((m) => m[1]);
    const errorTitle = titles.find((t) => t.includes("Продукт не найден"));
    const warningTitle = titles.find((t) => t.includes("Не задано количество на подвес"));
    expect(errorTitle).toBeDefined();
    expect(warningTitle).toBeDefined();
    // Каждый код — свой элемент блока, оба читаются в обрезанной ячейке.
    expect(cells.errors).toContain("Продукт не найден");
    expect(cells.errors).toContain("Количество должно быть положительным");
  });
});

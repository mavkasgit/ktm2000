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

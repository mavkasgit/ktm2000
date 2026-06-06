import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  allTimePreset,
  defaultDateRangePresets,
  findActivePreset,
  formatDateRu,
  formatInputDigits,
  parseRuDate,
} from "./date-range-presets";
import { DateRangePicker } from "./DateRangePicker";

describe("date-range-presets helpers", () => {
  it("formatDateRu converts ISO to DD.MM.YYYY", () => {
    expect(formatDateRu("2025-03-21")).toBe("21.03.2025");
    expect(formatDateRu("")).toBe("");
    expect(formatDateRu("not-a-date")).toBe("");
  });

  it("parseRuDate accepts valid DD.MM.YYYY", () => {
    expect(parseRuDate("21.03.2025")).toBe("2025-03-21");
    expect(parseRuDate("01.01.2000")).toBe("2000-01-01");
  });

  it("parseRuDate rejects invalid input", () => {
    expect(parseRuDate("")).toBeNull();
    expect(parseRuDate("21/03/2025")).toBeNull();
    expect(parseRuDate("1.03.2025")).toBeNull();
    expect(parseRuDate("21.3.2025")).toBeNull();
    expect(parseRuDate("31.13.2025")).toBeNull();
    expect(parseRuDate("32.01.2025")).toBeNull();
    expect(parseRuDate("31.02.2025")).toBeNull();
    expect(parseRuDate("00.00.0000")).toBeNull();
  });

  it("formatInputDigits auto-formats digits with dots", () => {
    expect(formatInputDigits("")).toBe("");
    expect(formatInputDigits("2")).toBe("2");
    expect(formatInputDigits("21032025")).toBe("21.03.2025");
    expect(formatInputDigits("21abc03xyz2025")).toBe("21.03.2025");
    expect(formatInputDigits("21032025000")).toBe("21.03.2025");
  });

  it("allTimePreset returns empty range", () => {
    expect(allTimePreset.getRange()).toEqual({ from: "", to: "" });
  });

  it("defaultDateRangePresets contains expected keys", () => {
    const keys = defaultDateRangePresets.map((p) => p.key);
    expect(keys).toEqual([
      "all",
      "today",
      "yesterday",
      "last7",
      "last30",
      "thisWeek",
      "prevWeek",
      "thisMonth",
      "prevMonth",
      "thisQuarter",
      "yearToDate",
    ]);
  });

  it("today preset returns the same day for from and to", () => {
    const today = defaultDateRangePresets.find((p) => p.key === "today")!;
    const { from, to } = today.getRange();
    expect(from).toBe(to);
  });

  it("thisWeek preset has from <= to and span of 7 days", () => {
    const preset = defaultDateRangePresets.find((p) => p.key === "thisWeek")!;
    const { from, to } = preset.getRange();
    expect(from).toBeTruthy();
    expect(to).toBeTruthy();
    expect(from <= to).toBe(true);
    const [fy, fm, fd] = from.split("-").map(Number);
    const [ty, tm, td] = to.split("-").map(Number);
    const fromDate = new Date(fy, fm - 1, fd);
    const toDate = new Date(ty, tm - 1, td);
    const diff = Math.round((toDate.getTime() - fromDate.getTime()) / 86_400_000);
    expect(diff).toBe(6);
  });

  it("findActivePreset returns null for non-matching range", () => {
    expect(findActivePreset({ from: "1999-01-01", to: "1999-01-02" })).toBeNull();
  });

  it("findActivePreset returns the all preset for empty range", () => {
    const preset = findActivePreset({ from: "", to: "" });
    expect(preset?.key).toBe("all");
  });

  it("findActivePreset returns matching preset by computed dates", () => {
    const todayPreset = defaultDateRangePresets.find((p) => p.key === "today")!;
    const range = todayPreset.getRange();
    const preset = findActivePreset(range);
    expect(preset?.key).toBe("today");
  });
});

describe("DateRangePicker", () => {
  it("renders 'Все время' preset label when range is empty", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="" to="" onChange={() => {}} />,
    );
    expect(html).toContain("Все время");
    expect(html).not.toContain("aria-label=\"Очистить период\"");
  });

  it("renders placeholder when range is empty and 'all' preset is omitted from presets", () => {
    const presets = defaultDateRangePresets.filter((p) => p.key !== "all");
    const html = renderToStaticMarkup(
      <DateRangePicker from="" to="" onChange={() => {}} presets={presets} />,
    );
    expect(html).toContain("Выберите период");
  });

  it("renders formatted range when both dates are set without matching preset", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="2025-03-21" to="2025-03-28" onChange={() => {}} />,
    );
    expect(html).toContain("21.03.2025 — 28.03.2025");
    expect(html).toContain("aria-label=\"Очистить период\"");
  });

  it("renders 'с ...' when only from is set", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="2025-03-21" to="" onChange={() => {}} />,
    );
    expect(html).toContain("с 21.03.2025");
  });

  it("renders 'по ...' when only to is set", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="" to="2025-03-28" onChange={() => {}} />,
    );
    expect(html).toContain("по 28.03.2025");
  });

  it("renders preset label when range matches a preset", () => {
    const today = defaultDateRangePresets.find((p) => p.key === "today")!;
    const { from, to } = today.getRange();
    const html = renderToStaticMarkup(
      <DateRangePicker from={from} to={to} onChange={() => {}} />,
    );
    expect(html).toContain("Сегодня");
    expect(html).toContain(formatDateRu(from));
  });

  it("uses custom placeholder when provided", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="" to="" onChange={() => {}} placeholder="Период смены" />,
    );
    expect(html).toContain("Период смены");
  });

  it("renders label when provided", () => {
    const html = renderToStaticMarkup(
      <DateRangePicker from="" to="" onChange={() => {}} label="Период" />,
    );
    expect(html).toContain("Период");
  });
});
